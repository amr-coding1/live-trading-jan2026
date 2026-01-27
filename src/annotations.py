"""Trade annotation management.

Provides CLI interface for adding pre-trade and post-trade
annotations to document trading decisions and lessons.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def create_annotation_template() -> dict:
    """Create empty annotation template.

    Returns:
        Dictionary with annotation structure.
    """
    return {
        "trade_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pre_trade": {
            "symbol": None,
            "thesis": None,
            "intended_entry": None,
            "position_size_rationale": None,
            "exit_plan": None,
        },
        "post_trade": {
            "outcome": None,
            "matched_expectation": None,
            "lesson": None,
        },
    }


def load_annotation(annotations_dir: str, trade_id: str) -> Optional[dict]:
    """Load existing annotation by trade ID.

    Args:
        annotations_dir: Path to annotations directory.
        trade_id: UUID of the trade.

    Returns:
        Annotation dictionary or None if not found.
    """
    ann_path = Path(annotations_dir) / f"{trade_id}.json"

    if not ann_path.exists():
        return None

    with open(ann_path) as f:
        return json.load(f)


def save_annotation(annotations_dir: str, annotation: dict) -> Path:
    """Save annotation to JSON file.

    Args:
        annotations_dir: Path to annotations directory.
        annotation: Annotation dictionary.

    Returns:
        Path to saved file.
    """
    ann_dir = Path(annotations_dir)
    ann_dir.mkdir(parents=True, exist_ok=True)

    trade_id = annotation["trade_id"]
    ann_path = ann_dir / f"{trade_id}.json"

    annotation["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(ann_path, "w") as f:
        json.dump(annotation, f, indent=2)

    return ann_path


def prompt_input(prompt: str, default: Optional[str] = None) -> Optional[str]:
    """Prompt user for input with optional default.

    Args:
        prompt: Prompt text to display.
        default: Default value if user enters nothing.

    Returns:
        User input or default value.
    """
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "

    value = input(display).strip()

    if not value and default:
        return default

    return value if value else None


def prompt_float(prompt: str, default: Optional[float] = None) -> Optional[float]:
    """Prompt user for float input.

    Args:
        prompt: Prompt text to display.
        default: Default value if user enters nothing.

    Returns:
        Float value or None.
    """
    default_str = str(default) if default is not None else None
    value = prompt_input(prompt, default_str)

    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        print(f"Invalid number: {value}")
        return prompt_float(prompt, default)


def prompt_bool(prompt: str, default: Optional[bool] = None) -> Optional[bool]:
    """Prompt user for yes/no input.

    Args:
        prompt: Prompt text to display.
        default: Default value if user enters nothing.

    Returns:
        Boolean value or None.
    """
    default_str = None
    if default is True:
        default_str = "y"
    elif default is False:
        default_str = "n"

    value = prompt_input(f"{prompt} (y/n)", default_str)

    if value is None:
        return None

    value = value.lower()
    if value in ("y", "yes", "true", "1"):
        return True
    elif value in ("n", "no", "false", "0"):
        return False
    else:
        print("Please enter y or n")
        return prompt_bool(prompt, default)


def annotate_pre_trade(annotation: dict) -> dict:
    """Interactive pre-trade annotation.

    Args:
        annotation: Annotation dictionary to update.

    Returns:
        Updated annotation dictionary.
    """
    print("\n--- PRE-TRADE ANNOTATION ---\n")

    pre = annotation["pre_trade"]

    pre["symbol"] = prompt_input("Symbol", pre.get("symbol"))
    pre["thesis"] = prompt_input("Trade thesis", pre.get("thesis"))
    pre["intended_entry"] = prompt_float("Intended entry price", pre.get("intended_entry"))
    pre["position_size_rationale"] = prompt_input(
        "Position size rationale",
        pre.get("position_size_rationale"),
    )
    pre["exit_plan"] = prompt_input("Exit plan", pre.get("exit_plan"))

    return annotation


def annotate_post_trade(annotation: dict) -> dict:
    """Interactive post-trade annotation.

    Args:
        annotation: Annotation dictionary to update.

    Returns:
        Updated annotation dictionary.
    """
    print("\n--- POST-TRADE ANNOTATION ---\n")

    post = annotation["post_trade"]

    post["outcome"] = prompt_input("Trade outcome", post.get("outcome"))
    post["matched_expectation"] = prompt_bool(
        "Did outcome match expectation?",
        post.get("matched_expectation"),
    )
    post["lesson"] = prompt_input("Lesson learned", post.get("lesson"))

    return annotation


def interactive_annotate(
    annotations_dir: str,
    trade_id: Optional[str] = None,
    pre_trade: bool = True,
    post_trade: bool = False,
) -> dict:
    """Run interactive annotation session.

    Args:
        annotations_dir: Path to annotations directory.
        trade_id: Existing trade ID to update, or None for new.
        pre_trade: Whether to prompt for pre-trade annotation.
        post_trade: Whether to prompt for post-trade annotation.

    Returns:
        Completed annotation dictionary.
    """
    if trade_id:
        annotation = load_annotation(annotations_dir, trade_id)
        if annotation:
            print(f"Updating existing annotation for trade {trade_id}")
        else:
            print(f"Creating new annotation with ID {trade_id}")
            annotation = create_annotation_template()
            annotation["trade_id"] = trade_id
    else:
        annotation = create_annotation_template()
        print(f"Creating new annotation with ID {annotation['trade_id']}")

    if pre_trade:
        annotation = annotate_pre_trade(annotation)

    if post_trade:
        annotation = annotate_post_trade(annotation)

    save_path = save_annotation(annotations_dir, annotation)
    print(f"\nAnnotation saved to: {save_path}")

    return annotation


def list_annotations(annotations_dir: str) -> list[dict]:
    """List all annotations with summary.

    Args:
        annotations_dir: Path to annotations directory.

    Returns:
        List of annotation summaries.
    """
    ann_dir = Path(annotations_dir)

    if not ann_dir.exists():
        return []

    annotations = []
    for json_file in ann_dir.glob("*.json"):
        if json_file.name.startswith("monthly"):
            continue

        try:
            with open(json_file) as f:
                data = json.load(f)
                annotations.append({
                    "trade_id": data.get("trade_id"),
                    "symbol": data.get("pre_trade", {}).get("symbol"),
                    "thesis": data.get("pre_trade", {}).get("thesis"),
                    "outcome": data.get("post_trade", {}).get("outcome"),
                    "created_at": data.get("created_at"),
                })
        except (json.JSONDecodeError, KeyError):
            continue

    return sorted(annotations, key=lambda x: x.get("created_at") or "", reverse=True)


def format_annotation_list(annotations: list[dict]) -> str:
    """Format annotation list for display.

    Args:
        annotations: List of annotation summaries.

    Returns:
        Formatted text output.
    """
    if not annotations:
        return "No annotations found."

    lines = [
        "=" * 60,
        "TRADE ANNOTATIONS",
        "=" * 60,
        "",
    ]

    for ann in annotations:
        lines.append(f"ID: {ann['trade_id']}")
        lines.append(f"  Symbol: {ann['symbol'] or 'N/A'}")
        lines.append(f"  Thesis: {(ann['thesis'] or 'N/A')[:50]}...")
        lines.append(f"  Outcome: {ann['outcome'] or 'Pending'}")
        lines.append("")

    return "\n".join(lines)
