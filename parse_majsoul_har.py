#!/usr/bin/env python3
import argparse
import ast
import base64
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path


SCALAR_TYPES = {
    "bool",
    "uint32",
    "int32",
    "sint32",
    "uint64",
    "int64",
    "sint64",
}

SHORT_DISCARD_KEY = bytes([0x9D, 0x7C, 0x71, 0x6A, 0x66, 0xD4, 0x66, 0x9C])
LONG_DISCARD_KEY = bytes([0xB1, 0x90, 0x85, 0x7E, 0x7A, 0xE8, 0x5A, 0xB1])
NONSELF_LONG_DISCARD_KEY = bytes([0xB7, 0x96, 0x8B, 0x84, 0x80, 0xEE])
SHORT_DEAL_KEY = {0: 0x95, 1: 0x74, 2: 0x69, 4: 0x2E, 5: 0xCC}
SELF_DEAL_KEY = bytes([0x92, 0x71, 0x66, 0x5F, 0x5B, 0xC9, 0x4B])
FIRST_ROUND_SELF_DEAL_KEY = bytes([0x93, 0x72, 0x67, 0x60, 0x5C, 0xCA, 0x4C])
LONG_SELF_DEAL_KEY = bytes([0xDE, 0xBD, 0xB2, 0xAB, 0xA7, 0x15, 0x97])
SHORT_CHI_PENG_KEY = bytes([0x90, 0x6F, 0x64, 0x5D, 0x59, 0xC7, 0x49, 0x8F])
ACTION_KEYS = [0x84, 0x5E, 0x4E, 0x42, 0x39, 0xA2, 0x1F, 0x60, 0x1C]


def parse_varint(buf, pos):
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("unexpected EOF while reading varint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7


def decode_signed(value, bits):
    sign_bit = 1 << (bits - 1)
    full = 1 << bits
    return value - full if value & sign_bit else value


def decode_scalar(value, field_type):
    if field_type == "bool":
        return bool(value)
    if field_type == "int32":
        return decode_signed(value, 32)
    if field_type == "int64":
        return decode_signed(value, 64)
    if field_type == "sint32":
        return (value >> 1) ^ -(value & 1)
    if field_type == "sint64":
        return (value >> 1) ^ -(value & 1)
    return value


def parse_packed_varints(buf, field_type):
    pos = 0
    values = []
    while pos < len(buf):
        value, pos = parse_varint(buf, pos)
        values.append(decode_scalar(value, field_type))
    return values


def decode_action_bytes(data):
    raw = bytearray(data)
    for i in range(len(raw)):
        mask = ((23 ^ len(raw)) + 5 * i + ACTION_KEYS[i % len(ACTION_KEYS)]) & 0xFF
        raw[i] ^= mask
    return bytes(raw)


def tile_text(raw):
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if len(text) != 2:
        return None
    if text[0] not in "1234567890":
        return None
    if text[1] not in "mpsz":
        return None
    return text


def format_seat(seat, seat_names=None):
    if seat is None:
        return "?"
    if seat_names and seat in seat_names:
        return f"{seat}({seat_names[seat]})"
    return str(seat)


class LiqiSchema:
    def __init__(self, liqi_root):
        self.root = liqi_root["nested"]["lq"]["nested"]

    def message(self, name):
        return self.root.get(name)

    def service_method(self, service, method):
        service_schema = self.root.get(service, {})
        methods = service_schema.get("methods", {})
        return methods.get(method)

    def decode_message(self, buf, message_name):
        schema = self.message(message_name)
        if not schema or "fields" not in schema:
            return {"_raw_hex": buf.hex(), "_decode_error": f"missing schema for {message_name}"}

        field_index = {field["id"]: (name, field) for name, field in schema["fields"].items()}
        pos = 0
        result = {}

        while pos < len(buf):
            try:
                key, pos = parse_varint(buf, pos)
            except ValueError as exc:
                result["_decode_error"] = str(exc)
                result["_raw_hex"] = buf.hex()
                return result

            field_id = key >> 3
            wire_type = key & 0x07
            field_meta = field_index.get(field_id)
            if not field_meta:
                result["_decode_error"] = f"unknown field id {field_id}"
                result["_raw_hex"] = buf.hex()
                return result

            field_name, field = field_meta
            field_type = field["type"]
            repeated = field.get("rule") == "repeated"

            try:
                if wire_type == 0:
                    value, pos = parse_varint(buf, pos)
                    value = decode_scalar(value, field_type)
                elif wire_type == 2:
                    size, pos = parse_varint(buf, pos)
                    raw = buf[pos:pos + size]
                    pos += size

                    if field_type == "string":
                        value = raw.decode("utf-8", errors="replace")
                    elif field_type == "bytes":
                        value = {
                            "_base64": base64.b64encode(raw).decode("ascii"),
                            "_hex": raw.hex(),
                        }
                    elif self.message(field_type):
                        value = self.decode_message(raw, field_type)
                    elif repeated and field_type in SCALAR_TYPES:
                        value = parse_packed_varints(raw, field_type)
                    else:
                        value = {"_hex": raw.hex()}
                else:
                    result["_decode_error"] = f"unsupported wire type {wire_type} on field {field_name}"
                    result["_raw_hex"] = buf.hex()
                    return result
            except Exception as exc:
                result["_decode_error"] = f"failed on field {field_name}: {exc}"
                result["_raw_hex"] = buf.hex()
                return result

            if repeated:
                bucket = result.setdefault(field_name, [])
                if wire_type == 2 and field_type in SCALAR_TYPES and isinstance(value, list):
                    bucket.extend(value)
                else:
                    bucket.append(value)
            else:
                result[field_name] = value

        return result


def parse_simple_protobuf(buf):
    pos = 0
    fields = []
    while pos < len(buf):
        tag = buf[pos]
        pos += 1
        field_id = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value, pos = parse_varint(buf, pos)
        elif wire_type == 2:
            size, pos = parse_varint(buf, pos)
            value = buf[pos:pos + size]
            pos += size
        else:
            raise ValueError(f"unsupported simple wire type {wire_type}")
        fields.append((field_id, wire_type, value))
    return fields


def parse_frame(raw):
    frame_type = raw[0]
    if frame_type == 1:
        wrapper = parse_simple_protobuf(raw[1:])
        message_id = None
    elif frame_type in (2, 3):
        message_id = struct.unpack("<H", raw[1:3])[0]
        wrapper = parse_simple_protobuf(raw[3:])
    else:
        raise ValueError(f"unknown frame type {frame_type}")

    method = ""
    body = b""
    for field_id, wire_type, value in wrapper:
        if field_id == 1 and wire_type == 2:
            method = value.decode("utf-8", errors="replace")
        elif field_id == 2 and wire_type == 2:
            body = value

    return frame_type, message_id, method, body


def extract_liqi_schema(har):
    for entry in har["log"]["entries"]:
        url = entry.get("request", {}).get("url", "")
        if "liqi.json" in url:
            return json.loads(entry["response"]["content"]["text"])
    raise ValueError("liqi.json not found in HAR")


def extract_game_gateway_messages(har):
    for entry in har["log"]["entries"]:
        url = entry.get("request", {}).get("url", "")
        if "game-gateway" in url:
            return entry.get("_webSocketMessages", [])
    raise ValueError("game-gateway websocket not found in HAR")


def decode_action_prototype(schema, body):
    wrapper = schema.decode_message(body, "ActionPrototype")
    action_name = wrapper.get("name", "")
    action_data = wrapper.get("data")
    if isinstance(action_data, dict) and "_base64" in action_data:
        raw = base64.b64decode(action_data["_base64"])
        decoded_candidates = []
        if action_name:
            decoded_candidates.append(("plain", schema.decode_message(raw, action_name), raw))
            transformed = decode_action_bytes(raw)
            if transformed != raw:
                decoded_candidates.append(("decoded", schema.decode_message(transformed, action_name), transformed))
        chosen = None
        for source, decoded, payload in decoded_candidates:
            if action_decode_looks_valid(action_name, decoded):
                chosen = (source, decoded, payload)
                break
        if chosen:
            source, decoded, payload = chosen
            wrapper["data"] = decoded
            wrapper["data_source"] = source
            if source != "plain":
                wrapper["data_raw_hex"] = raw.hex()
                wrapper["data_decoded_hex"] = payload.hex()
        else:
            heuristic = heuristic_decode_action_data(action_name, raw)
            if heuristic:
                wrapper["data"] = heuristic
            if decoded_candidates:
                wrapper["data_decoded"] = decoded_candidates[-1][1]
            wrapper["data_raw_hex"] = raw.hex()
    return wrapper


def xor_prefix(raw, key):
    size = min(len(raw), len(key))
    return bytes(raw[i] ^ key[i] for i in range(size))


def heuristic_decode_action_data(action_name, raw):
    if action_name == "ActionDiscardTile":
        for key in (SHORT_DISCARD_KEY, LONG_DISCARD_KEY):
            prefix = xor_prefix(raw, key)
            if len(prefix) < 8:
                continue
            if prefix[0] == 0x08 and prefix[2] == 0x12 and prefix[3] == 0x02:
                tile = tile_text(prefix[4:6])
                if tile:
                    return {
                        "seat": prefix[1],
                        "tile": tile,
                        "_heuristic": True,
                    }
        prefix = xor_prefix(raw, NONSELF_LONG_DISCARD_KEY)
        if len(prefix) >= 6 and prefix[0] == 0x08 and prefix[2] == 0x12 and prefix[3] == 0x02:
            tile = tile_text(prefix[4:6])
            if tile:
                return {
                    "seat": prefix[1],
                    "tile": tile,
                    "_heuristic": True,
                }

    if action_name == "ActionDealTile":
        if len(raw) == 6:
            if (
                (raw[0] ^ SHORT_DEAL_KEY[0]) == 0x08
                and (raw[2] ^ SHORT_DEAL_KEY[2]) == 0x18
                and (raw[4] ^ SHORT_DEAL_KEY[4]) == 0x48
                and (raw[5] ^ SHORT_DEAL_KEY[5]) == 0x00
            ):
                return {
                    "seat": raw[1] ^ SHORT_DEAL_KEY[1],
                    "_heuristic": True,
                }

        for key in (SELF_DEAL_KEY, FIRST_ROUND_SELF_DEAL_KEY, LONG_SELF_DEAL_KEY):
            prefix = xor_prefix(raw, key)
            if len(prefix) < 7:
                continue
            if prefix[0] == 0x08 and prefix[2] == 0x12 and prefix[3] == 0x02 and prefix[6] == 0x18:
                tile = tile_text(prefix[4:6])
                if tile:
                    return {
                        "seat": prefix[1],
                        "tile": tile,
                        "_heuristic": True,
                    }

    if action_name == "ActionChiPengGang":
        prefix = xor_prefix(raw, SHORT_CHI_PENG_KEY)
        if len(prefix) >= 8 and prefix[0] == 0x08 and prefix[2] == 0x10 and prefix[4] == 0x1A and prefix[5] == 0x02:
            tile = tile_text(prefix[6:8])
            if tile:
                return {
                    "seat": prefix[1],
                    "type": prefix[3],
                    "tiles": [tile],
                    "_heuristic": True,
                }

    return None


def action_decode_looks_valid(action_name, decoded):
    if not isinstance(decoded, dict) or "_decode_error" in decoded:
        return False

    required_keys = {
        "ActionDiscardTile": ("seat", "tile"),
        "ActionDealTile": ("seat", "left_tile_count"),
        "ActionChiPengGang": ("seat", "type"),
        "ActionAnGangAddGang": ("seat", "type"),
        "ActionNewRound": ("chang", "ju", "ben"),
        "ActionHule": ("hules",),
    }
    needed = required_keys.get(action_name)
    if not needed:
        return True
    return any(key in decoded for key in needed)


def decode_message_body(schema, method_name, body, frame_type):
    if not method_name:
        return {}

    parts = method_name.split(".")
    if len(parts) < 4:
        return {}

    _, lq_name, service_name, rpc_name = parts
    if lq_name != "lq":
        return {}

    method_info = schema.service_method(service_name, rpc_name)
    if not method_info:
        return {}

    if frame_type == 2:
        message_type = method_info["requestType"]
    else:
        message_type = method_info["responseType"]

    return schema.decode_message(body, message_type)


def summarize_action(action, seat_names=None):
    name = action.get("name", "Action?")
    decoded = action.get("data")
    if not isinstance(decoded, dict):
        return name

    seat = decoded.get("seat")
    if name == "ActionDiscardTile":
        tile = decoded.get("tile", "?")
        suffix = " moqie" if decoded.get("moqie") else ""
        return f"{name} seat={format_seat(seat, seat_names)} tile={tile}{suffix}"
    if name == "ActionDealTile":
        tile = decoded.get("tile")
        left = decoded.get("left_tile_count")
        parts = [f"seat={format_seat(seat, seat_names)}"]
        if tile:
            parts.append(f"tile={tile}")
        if left is not None:
            parts.append(f"left={left}")
        return f"{name} " + " ".join(parts)
    if name == "ActionChiPengGang":
        type_value = decoded.get("type")
        type_text = {0: "chi", 1: "peng", 2: "daiminkan"}.get(type_value, type_value)
        return f"{name} seat={format_seat(seat, seat_names)} type={type_text} tiles={decoded.get('tiles')}"
    if name == "ActionAnGangAddGang":
        return (
            f"{name} seat={format_seat(seat, seat_names)} "
            f"type={decoded.get('type')} tiles={decoded.get('tiles')}"
        )
    if name == "ActionNewRound":
        doras = decoded.get("doras") or ([] if decoded.get("dora") is None else [decoded.get("dora")])
        tiles = decoded.get("tiles") or []
        return (
            f"{name} chang={decoded.get('chang')} ju={decoded.get('ju')} "
            f"ben={decoded.get('ben')} doras={doras} left={decoded.get('left_tile_count')} "
            f"tiles={tiles}"
        )
    if name == "ActionHule":
        return f"{name} hules={len(decoded.get('hules', []))}"
    return name


def summarize_request(method, decoded):
    if method.endswith(".inputOperation"):
        tile = decoded.get("tile")
        op_type = decoded.get("type")
        moqie = decoded.get("moqie")
        return f"inputOperation type={op_type} tile={tile} moqie={moqie}"
    if method.endswith(".inputChiPengGang"):
        if decoded.get("cancel_operation"):
            return f"inputChiPengGang cancel=True timeuse={decoded.get('timeuse')}"
        return f"inputChiPengGang type={decoded.get('type')} index={decoded.get('index')}"
    return method.split(".")[-1]


def render_timeline_item(item, seat_names=None):
    if item["kind"] == "text":
        return item["text"]
    return f"[{item['index']:04d}] {summarize_action(item['action'], seat_names)}"


def extract_round_header_text(text):
    if "ActionNewRound" not in text:
        return None
    marker = "ActionNewRound "
    pos = text.find(marker)
    return text[pos + len(marker):] if pos != -1 else None


def format_round_name(chang, ju):
    winds = ["东", "南", "西", "北"]
    wind = winds[chang] if isinstance(chang, int) and 0 <= chang < len(winds) else f"场{chang}"
    hand = (ju + 1) if isinstance(ju, int) else ju
    return f"{wind}{hand}局"


def parse_round_header_line(line):
    body = extract_round_header_text(line)
    if not body:
        return {}

    result = {}
    for key in ("chang", "ju", "ben", "left"):
        match = re.search(rf"{key}=([0-9]+)", body)
        if match:
            result[key] = int(match.group(1))

    doras_match = re.search(r"doras=(\[[^\]]*\])", body)
    if doras_match:
        result["doras"] = ast.literal_eval(doras_match.group(1))

    tiles_match = re.search(r"tiles=(\[[^\]]*\])", body)
    if tiles_match:
        result["tiles"] = ast.literal_eval(tiles_match.group(1))

    return result


def build_report(path):
    har = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        schema = LiqiSchema(extract_liqi_schema(har))
    except ValueError as exc:
        return (
            f"HAR: {path}\n"
            f"Error: {exc}\n"
            "这个 HAR 只有 websocket，不带页面里的 liqi.json，无法做结构化完整解析。\n"
            "请优先使用带资源的 HAR，例如你后面抓到的 game.maj-soul.com3.har。\n"
        )
    messages = extract_game_gateway_messages(har)

    pending_requests = {}
    player_lookup = {}
    self_account_id = None
    self_seat = None
    game_config = None
    seat_list = []
    timeline_items = []
    action_counter = Counter()
    request_counter = Counter()
    pending_self_call = None
    last_deal_seat = None
    last_discard_data = None
    last_action_name = None
    last_action_data = None

    for index, message in enumerate(messages):
        raw = base64.b64decode(message["data"])
        frame_type, request_id, method_name, body = parse_frame(raw)

        if frame_type == 2:
            pending_requests[request_id] = method_name
            decoded = decode_message_body(schema, method_name, body, frame_type)
            request_counter[method_name] += 1
            if method_name.endswith(".authGame"):
                self_account_id = decoded.get("account_id")
            if method_name.endswith(".inputOperation") or method_name.endswith(".inputChiPengGang"):
                timeline_items.append({
                    "kind": "text",
                    "text": f"[{index:04d}] YOU {summarize_request(method_name, decoded)}",
                })
            if method_name.endswith(".inputChiPengGang"):
                pending_self_call = decoded

        elif frame_type == 3:
            request_method = pending_requests.get(request_id, "")
            decoded = decode_message_body(schema, request_method, body, frame_type)
            if request_method.endswith(".authGame"):
                players = decoded.get("players", [])
                for player in players:
                    player_lookup[player.get("account_id")] = player.get("nickname")
                seat_list = decoded.get("seat_list", [])
                if self_account_id in seat_list:
                    self_seat = seat_list.index(self_account_id)
                game_config = decoded.get("game_config")

        elif frame_type == 1:
            if method_name == ".lq.ActionPrototype":
                action = decode_action_prototype(schema, body)
                action_data = action.get("data")
                if action.get("name") == "ActionDealTile" and isinstance(action_data, dict):
                    if action_data.get("seat") is None and isinstance(last_discard_data, dict):
                        prev_seat = last_discard_data.get("seat")
                        if prev_seat is not None and player_lookup:
                            action_data["seat"] = (prev_seat + 1) % len(player_lookup)
                            action_data["_inferred_seat_from_rotation"] = True
                if action.get("name") == "ActionDiscardTile" and isinstance(action_data, dict):
                    if action_data.get("seat") is None and last_deal_seat is not None:
                        action_data["seat"] = last_deal_seat
                        action_data["_inferred_seat_from_turn"] = True
                    if (
                        action_data.get("seat") is None
                        and last_action_name == "ActionChiPengGang"
                        and isinstance(last_action_data, dict)
                        and last_action_data.get("seat") is not None
                    ):
                        action_data["seat"] = last_action_data.get("seat")
                        action_data["_inferred_seat_from_call"] = True
                if (
                    action.get("name") == "ActionChiPengGang"
                    and pending_self_call
                    and isinstance(action.get("data"), dict)
                    and action["data"].get("seat") is None
                    and self_seat is not None
                ):
                    inferred_type = pending_self_call.get("type")
                    if inferred_type == 2:
                        inferred_type = 0
                    elif inferred_type == 3:
                        inferred_type = 1
                    action["data"]["seat"] = self_seat
                    if inferred_type is not None:
                        action["data"]["type"] = inferred_type
                    action["data"]["_inferred_from_request"] = True
                if (
                    action.get("name") == "ActionChiPengGang"
                    and isinstance(action.get("data"), dict)
                    and not action["data"].get("tiles")
                    and isinstance(last_discard_data, dict)
                    and last_discard_data.get("tile")
                ):
                    action["data"]["tiles"] = [last_discard_data["tile"]]
                    action["data"]["_inferred_tiles_from_previous_discard"] = True
                action_counter[action.get("name", "Action?")] += 1
                item = {"kind": "action", "index": index, "action": action}
                if (
                    action.get("name") == "ActionChiPengGang"
                    and isinstance(action.get("data"), dict)
                    and action["data"].get("tiles")
                    and timeline_items
                ):
                    prev = timeline_items[-1]
                    if prev.get("kind") == "action":
                        prev_action = prev["action"]
                        prev_data = prev_action.get("data")
                        if (
                            prev_action.get("name") == "ActionDiscardTile"
                            and isinstance(prev_data, dict)
                            and (prev_data.get("tile") in (None, "?"))
                        ):
                            tiles = action["data"].get("tiles") or []
                            if tiles:
                                prev_data["tile"] = tiles[0]
                                prev_data["_inferred_tile_from_call"] = True
                timeline_items.append(item)
                if action.get("name") == "ActionDealTile" and isinstance(action_data, dict):
                    last_deal_seat = action_data.get("seat")
                elif action.get("name") == "ActionDiscardTile":
                    last_deal_seat = None
                    last_discard_data = action_data if isinstance(action_data, dict) else None
                if action.get("name") == "ActionChiPengGang":
                    pending_self_call = None
                last_action_name = action.get("name")
                last_action_data = action_data if isinstance(action_data, dict) else None
            elif method_name == ".lq.NotifyGameEndResult":
                decoded = schema.decode_message(body, "NotifyGameEndResult")
                timeline_items.append({"kind": "text", "text": f"[{index:04d}] NotifyGameEndResult"})
                if isinstance(decoded, dict):
                    timeline_items.append({"kind": "text", "text": f"         raw={json.dumps(decoded, ensure_ascii=False)}"})

    lines = []
    lines.append(f"HAR: {path}")
    lines.append(f"Messages: {len(messages)}")
    lines.append("")

    if self_account_id is not None:
        lines.append(f"Self account: {self_account_id}")
    if self_seat is not None:
        lines.append(f"Self seat: {self_seat}")
    if game_config:
        mode = game_config.get("mode", {})
        meta = game_config.get("meta", {})
        lines.append(
            "Game config: "
            f"category={game_config.get('category')} "
            f"mode={mode.get('mode')} "
            f"mode_id={meta.get('mode_id')}"
        )
        seat_count = 0
        if player_lookup:
            seat_count = len(player_lookup)
        if seat_count:
            lines.append(f"Player count: {seat_count}")
    if player_lookup:
        lines.append("Players:")
        for account_id, nickname in player_lookup.items():
            suffix = " (you)" if account_id == self_account_id else ""
            lines.append(f"  - {account_id}: {nickname}{suffix}")
    if seat_list and player_lookup:
        lines.append("Seat map:")
        for seat, account_id in enumerate(seat_list):
            nickname = player_lookup.get(account_id, f"account:{account_id}")
            suffix = " (you)" if account_id == self_account_id else ""
            lines.append(f"  - seat {seat}: {nickname}{suffix}")
    lines.append("")

    if action_counter:
        lines.append("Action counts:")
        for name, count in action_counter.most_common():
            lines.append(f"  - {name}: {count}")
        lines.append("")

    if request_counter:
        lines.append("Request counts:")
        for name, count in request_counter.most_common():
            lines.append(f"  - {name}: {count}")
        lines.append("")

    lines.append("Timeline:")
    seat_names = {
        seat: player_lookup.get(account_id, f"account:{account_id}")
        for seat, account_id in enumerate(seat_list)
    }
    lines.extend(f"  {render_timeline_item(item, seat_names)}" for item in timeline_items)
    return "\n".join(lines)


def build_round_report(path):
    report = build_report(path)
    lines = report.splitlines()

    players = []
    seats = []
    grouped = []
    current = None

    for line in lines:
        if line.startswith("  - seat "):
            seats.append(line[4:])
        elif line.startswith("  - ") and ": " in line and "Players:" not in line:
            if any(tag in line for tag in ["(you)", "guanto", "厚入莲利帝斯", "春来夏去凝如霜"]):
                players.append(line[4:])

        if line.startswith("  [") and "ActionNewRound" in line:
            parsed = parse_round_header_line(line.strip())
            chang = parsed.get("chang")
            ju = parsed.get("ju")
            ben = parsed.get("ben")
            title = format_round_name(chang, ju)
            current = {
                "title": title,
                "header": line.strip(),
                "ben": ben,
                "parsed": parsed,
                "events": [],
            }
            grouped.append(current)
            continue

        if current and line.startswith("  ["):
            current["events"].append(line.strip())
        elif current and line.startswith("           raw="):
            current["events"].append(line.strip())

    out = []
    out.append(f"HAR: {path}")
    out.append("")
    if players:
        out.append("Players:")
        out.extend(f"  - {p}" for p in players)
        out.append("")
    if seats:
        out.append("Seat map:")
        out.extend(f"  - {s}" for s in seats)
        out.append("")
    for round_info in grouped:
        ben_suffix = f" {round_info['ben']}本场" if round_info["ben"] is not None else ""
        out.append(f"## {round_info['title']}{ben_suffix}")
        parsed = round_info.get("parsed", {})
        doras = parsed.get("doras")
        if doras:
            out.append(f"宝牌: {' '.join(doras)}")
        if parsed.get("left") is not None:
            out.append(f"牌山剩余: {parsed['left']}")
        tiles = parsed.get("tiles")
        if tiles:
            out.append(f"你的起手: {' '.join(tiles)}")
        out.append("")
        out.extend(round_info["events"])
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Parse Majsoul HAR websocket data into a readable timeline.")
    parser.add_argument("har", help="Path to HAR file")
    parser.add_argument("-o", "--output", help="Write report to file instead of stdout")
    parser.add_argument("--rounds", action="store_true", help="Write grouped round-by-round report")
    args = parser.parse_args()

    report = build_round_report(args.har) if args.rounds else build_report(args.har)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
        if not report.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
