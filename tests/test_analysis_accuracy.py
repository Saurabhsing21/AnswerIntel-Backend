"""The scoring behind scripts.eval_analysis. No AI calls: it only compares labels with verdicts."""

import pytest

from scripts.eval_analysis import predictions_from_result, report, score, usable_label


def item(i, label, predicted, brand="Acme"):
    return {"id": i, "brand": brand, "label": usable_label(label), "predicted": predicted}


def verdict(mentioned=True, recommended=False, position=None, sentiment="neutral"):
    return {"mentioned": mentioned, "recommended": recommended, "position": position, "sentiment": sentiment if mentioned else None}


def test_accuracy_precision_and_recall_per_field():
    items = [
        item(1, verdict(True, True, 1, "positive"), verdict(True, True, 1, "positive")),    # all right
        item(2, verdict(True, True, 2, "positive"), verdict(True, False, 2, "neutral")),    # missed a recommendation
        item(3, verdict(True, False, None, "neutral"), verdict(True, True, None, "neutral")),  # invented a recommendation
        item(4, verdict(False), verdict(False)),
        item(5, verdict(True, False, None, "negative"), verdict(False)),                     # missed a mention
    ]
    fields = score(items)["fields"]
    assert fields["mentioned"] == {"n": 5, "accuracy": 0.8, "precision": 1.0, "recall": 0.75}
    # recommended: labelled yes on 1 and 2, predicted yes on 1 and 3 -> one right of two predicted, one right of two labelled.
    assert fields["recommended"] == {"n": 5, "accuracy": 0.6, "precision": 0.5, "recall": 0.5}
    # position: every rank matches (items 3 to 5 have none on both sides).
    assert fields["position"] == {"n": 5, "accuracy": 1.0, "precision": 1.0, "recall": 1.0}
    # sentiment: items 2 (positive vs neutral) and 5 (negative vs none) are wrong; 3 of 5 match.
    assert fields["sentiment"]["accuracy"] == 0.6


def test_disagreements_list_every_miss():
    items = [
        item(7, verdict(True, True, 1, "positive"), verdict(True, False, 1, "positive"), brand="Acme"),
        item(8, verdict(False), verdict(True, False, None, "neutral"), brand="HubSpot"),
    ]
    found = score(items)["disagreements"]
    assert {"id": 7, "brand": "Acme", "field": "recommended", "labelled": True, "predicted": False} in found
    assert {"id": 8, "brand": "HubSpot", "field": "mentioned", "labelled": False, "predicted": True} in found
    assert {"id": 8, "brand": "HubSpot", "field": "sentiment", "labelled": None, "predicted": "neutral"} in found
    assert len(found) == 3


def test_a_wrong_rank_is_a_miss_for_both_precision_and_recall():
    fields = score([item(1, verdict(True, True, 2, "positive"), verdict(True, True, 3, "positive"))])["fields"]
    assert fields["position"] == {"n": 1, "accuracy": 0.0, "precision": 0.0, "recall": 0.0}


def test_no_positives_gives_none_not_a_division_error():
    fields = score([item(1, verdict(False), verdict(False))])["fields"]
    assert fields["recommended"] == {"n": 1, "accuracy": 1.0, "precision": None, "recall": None}
    assert score([])["fields"]["mentioned"] == {"n": 0, "accuracy": None, "precision": None, "recall": None}


def test_labels_are_normalised_and_checked():
    assert usable_label({"mentioned": None, "recommended": None, "position": None, "sentiment": None}) is None  # not labelled yet
    # An absent brand needs nothing else filled in.
    assert usable_label({"mentioned": False}) == verdict(False)
    with pytest.raises(ValueError):
        usable_label({"mentioned": True, "recommended": None, "position": None, "sentiment": "neutral"})
    with pytest.raises(ValueError):
        usable_label({"mentioned": True, "recommended": True, "position": None, "sentiment": "great"})
    with pytest.raises(ValueError):
        usable_label({"mentioned": True, "recommended": True, "position": 0, "sentiment": "positive"})


def test_predictions_are_read_from_the_analysis_result():
    result = {
        "mention": {"mentioned": True, "brand_name": "Acme"},
        "recommendation": {"recommended": True},
        "position": {"position": 2},
        "sentiment": {"sentiment": "positive"},
        "competitors": [{"competitor_name": "HubSpot", "mentioned": False, "recommended": False, "position": None, "sentiment": None}],
    }
    assert predictions_from_result(result) == {
        "Acme": {"mentioned": True, "recommended": True, "position": 2, "sentiment": "positive"},
        "HubSpot": {"mentioned": False, "recommended": False, "position": None, "sentiment": None},
    }


def test_report_points_to_the_model_switch_below_ninety_percent():
    low = score([item(1, verdict(True, True, 1, "positive"), verdict(True, False, 1, "positive"))])
    assert "openai/gpt-5.4-mini" in report(low, "m")
    good = score([item(1, verdict(True, True, 1, "positive"), verdict(True, True, 1, "positive"))])
    assert "openai/gpt-5.4-mini" not in report(good, "m")
