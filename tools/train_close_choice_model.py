#!/usr/bin/env python3
import argparse
import json
import random
from pathlib import Path

from close_choice_data import DEFAULT_DATASETS, build_examples


def parse_args():
    parser = argparse.ArgumentParser(description="Train a lightweight endgame close-choice evaluator.")
    parser.add_argument(
        "--dataset",
        action="append",
        nargs=2,
        metavar=("FAST_JSONL", "COMPARE_JSON"),
        help="Pair of fast replay JSONL and fast-vs-refined compare JSON.",
    )
    parser.add_argument(
        "--output",
        default="/Users/bigo/code/mj/data/archive/close_choice_model.json",
        help="Output JSON path for learned weights.",
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=1.0)
    parser.add_argument(
        "--max-abs-weight",
        type=float,
        default=0.0,
        help="Optional absolute cap for each learned weight; 0 disables clipping.",
    )
    return parser.parse_args()

def dot(weights, feats):
    return sum(weights.get(name, 0.0) * value for name, value in feats.items())


def accuracy(weights, bias, rows):
    if not rows:
        return 0.0
    correct = 0
    for feats, label in rows:
        score = dot(weights, feats) + bias
        pred = 1 if score >= 0 else -1
        if pred == label:
            correct += 1
    return round(correct / len(rows), 4)

def clip_weights(weights, max_abs_weight):
    if not max_abs_weight or max_abs_weight <= 0:
        return
    cap = float(max_abs_weight)
    for name, value in list(weights.items()):
        if value > cap:
            weights[name] = cap
        elif value < -cap:
            weights[name] = -cap


def train_averaged_perceptron(examples, epochs, seed, learning_rate=1.0, max_abs_weight=0.0):
    rng = random.Random(seed)
    rows = list(examples)
    rng.shuffle(rows)
    split = max(1, int(len(rows) * 0.8))
    train_rows = rows[:split]
    val_rows = rows[split:] or rows[:split]
    weights = {}
    bias = 0.0
    avg_weights = {}
    avg_bias = 0.0
    steps = 0
    best = None

    for _ in range(epochs):
        rng.shuffle(train_rows)
        for feats, label in train_rows:
            score = dot(weights, feats) + bias
            if label * score <= 0:
                for name, value in feats.items():
                    weights[name] = weights.get(name, 0.0) + learning_rate * label * value
                clip_weights(weights, max_abs_weight)
                bias += learning_rate * label
            steps += 1
            for name, value in weights.items():
                avg_weights[name] = avg_weights.get(name, 0.0) + value
            avg_bias += bias
        cur_weights = {name: value / steps for name, value in avg_weights.items()}
        cur_bias = avg_bias / steps if steps else 0.0
        train_acc = accuracy(cur_weights, cur_bias, train_rows)
        val_acc = accuracy(cur_weights, cur_bias, val_rows)
        candidate = (val_acc, train_acc, cur_weights, cur_bias)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    val_acc, train_acc, best_weights, best_bias = best
    pruned = {name: round(value, 6) for name, value in best_weights.items() if abs(value) >= 0.02}
    return pruned, round(best_bias, 6), train_acc, val_acc


def main():
    args = parse_args()
    datasets = args.dataset or DEFAULT_DATASETS
    examples, stats = build_examples(datasets)
    if not examples:
        raise SystemExit("No eligible close-choice examples found.")
    weights, bias, train_acc, val_acc = train_averaged_perceptron(
        examples,
        args.epochs,
        args.seed,
        args.learning_rate,
        args.max_abs_weight,
    )
    payload = {
        "version": 1,
        "scope": "all_last_close_choice",
        "datasets": datasets,
        "bias": bias,
        "weights": weights,
        "training": {
            **stats,
            "epochs": args.epochs,
            "seed": args.seed,
            "learning_rate": args.learning_rate,
            "max_abs_weight": args.max_abs_weight,
            "train_accuracy": train_acc,
            "validation_accuracy": val_acc,
        },
    }
    out = Path(args.output)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), **payload["training"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
