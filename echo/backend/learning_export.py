"""Versioned, read-only learning profile export. No model calls or configuration secrets."""
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from echo.backend import paths
from echo.backend.mindmap import is_placeholder_topic

FORMAT = "echo.learning-profile"
SCHEMA_VERSION = "2.0.0"
from echo.version import VERSION as APP_VERSION
SECTIONS = ("profile", "mastery", "difficulties", "reviews", "preferences")


def _id(kind, value):
    return kind + "_" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _time(value):
    number = _number(value)
    try:
        return datetime.fromtimestamp(number, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z") if number is not None and number > 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def _count(value):
    number = _number(value)
    return max(0, int(number)) if number is not None else 0


def _read(name, expected):
    try:
        with (Path(paths.config_dir()) / name).open(encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return expected()
    except (OSError, ValueError) as exc:
        raise ValueError(f"{name} 无法读取，请先检查原始学习记录；未修改该文件。") from exc
    if not isinstance(data, expected):
        raise ValueError(f"{name} 的数据格式不正确；未修改该文件。")
    return data


def _subject(title):
    for sep in ("·", "：", ":", "，", ",", "－", "-"):
        if sep in title:
            return title.split(sep, 1)[0].strip() or None
    return title or None


def _state(point):
    observations = point["observations"]
    latest = observations[-1] if observations else None
    review = point.get("review")
    if review and (not latest or (review["last_reviewed_at"] or review["recorded_at"] or "") >= (latest["observed_at"] or "")):
        result = review["last_result"]
        if result in ("again", "fuzzy") or not review["reviewed"]:
            return "weakness", ["最近复习仍未理解或不够清楚"]
        if result == "clear" and review["level"] >= 2:
            return "strength", ["最近自评清楚，且复习阶梯达到2级以上"]
        return "developing", ["近期已复习，但仍需更多确认"]
    if latest:
        mastery, status = latest["mastery"], latest["status"]
        if status in ("review", "warn") or mastery is not None and mastery < .6:
            return "weakness", ["最近课程记录提示待复习或掌握度低于0.6"]
        if status == "ok" and mastery is not None and mastery >= .8:
            return "strength", ["最近课程标记已跟上，掌握度至少0.8"]
        return "developing", ["已有学习记录，尚不足以归为相对掌握"]
    return "unknown", ["暂无足够记录"]


def _build_evidence_snapshot(now=None):
    profile = _read("profile.json", dict)
    raw_lessons = _read("lessons.json", list)
    raw_reviews = _read("review.json", list)
    warnings = []
    lessons, points, lookup = [], {}, {}
    ordered = sorted((row for row in raw_lessons if isinstance(row, dict)), key=lambda row: _number(row.get("time")) or 0)
    for index, raw in enumerate(ordered):
        title = _text(raw.get("title")) or "未命名课程"
        subject = _subject(title)
        lesson_id = _id("lesson", f"{raw.get('time')}\0{title}\0{index if not raw.get('time') else ''}")
        quiz = raw.get("quiz") if isinstance(raw.get("quiz"), dict) else {}
        total = _count(quiz.get("total"))
        correct = min(total, _count(quiz.get("correct")))
        lesson = {"id": lesson_id, "title": title, "subject": subject, "ended_at": _time(raw.get("time")),
                  "duration_seconds": max(0, _number(raw.get("duration")) or 0),
                  "summary": _text(raw.get("summary")), "knowledge_ids": [],
                  "quiz": {"total": total, "correct": correct, "accuracy": correct / total if total else None}}
        skills = raw.get("skills_detail")
        for skill in skills if isinstance(skills, list) else []:
            if not isinstance(skill, dict) or is_placeholder_topic(_text(skill.get("name"))):
                continue
            topic = _text(skill["name"])
            key = ((subject or "").casefold(), topic.casefold())
            if key not in points:
                points[key] = {"id": _id("knowledge", "\0".join(key)), "topic": topic, "subject": subject,
                               "observations": [], "review": None}
                lookup.setdefault(topic.casefold(), []).append(key)
            point = points[key]
            mastery = _number(skill.get("mastery"))
            if mastery is not None and not 0 <= mastery <= 1:
                warnings.append(f"{lesson_id}: {topic} 的掌握度超出0至1范围，已按未知导出。")
                mastery = None
            point["observations"].append({"lesson_id": lesson_id, "observed_at": lesson["ended_at"],
                                          "mastery": mastery, "status": _text(skill.get("status")) or "unknown",
                                          "source": "lesson_summary"})
            if point["id"] not in lesson["knowledge_ids"]:
                lesson["knowledge_ids"].append(point["id"])
        lessons.append(lesson)

    reviews = []
    for raw in raw_reviews:
        if not isinstance(raw, dict) or is_placeholder_topic(_text(raw.get("topic"))):
            continue
        topic = _text(raw["topic"])
        candidates = lookup.get(topic.casefold(), [])
        # Review records do not store a subject. Never assign a shared name to
        # one of several unrelated subjects just because it was encountered first.
        if len(candidates) == 1:
            point = points[candidates[0]]
        else:
            key = ("", topic.casefold())
            if key not in points:
                points[key] = {"id": _id("knowledge", "\0".join(key)), "topic": topic, "subject": None,
                               "observations": [], "review": None}
            point = points[key]
        review = {"id": _id("review", topic.casefold()), "knowledge_id": point["id"], "topic": topic,
                  "missing": _text(raw.get("missing")), "reason": _text(raw.get("reason")),
                  "source": _text(raw.get("source")) or "lesson_feedback",
                  "reviewed": raw.get("reviewed") is True, "review_sessions": _count(raw.get("review_count")),
                  "last_result": raw.get("last_result") if raw.get("last_result") in ("again", "fuzzy", "clear") else None,
                  "level": _count(raw.get("level")), "recorded_at": _time(raw.get("time")),
                  "last_reviewed_at": _time(raw.get("reviewed_at")), "next_review_at": _time(raw.get("due"))}
        reviews.append(review)
        point["review"] = review

    knowledge = []
    recurring = []
    for point in points.values():
        point["state"], point["reasons"] = _state(point)
        point["latest_mastery"] = point["observations"][-1]["mastery"] if point["observations"] else None
        difficulty_lessons = list(dict.fromkeys(o["lesson_id"] for o in point["observations"]
                                              if o["status"] in ("review", "warn", "fixed")
                                              or o["mastery"] is not None and o["mastery"] < .6))
        point["difficulty_lesson_ids"] = difficulty_lessons
        if len(difficulty_lessons) >= 2:
            recurring.append({"knowledge_id": point["id"], "topic": point["topic"],
                              "affected_lesson_count": len(difficulty_lessons), "lesson_ids": difficulty_lessons,
                              "basis": "difficulty_in_multiple_saved_lessons"})
        knowledge.append(point)
    knowledge.sort(key=lambda point: ((point["subject"] or ""), point["topic"]))
    recurring.sort(key=lambda item: (-item["affected_lesson_count"], item["topic"]))
    profile_created = _number(profile.get("created"))
    personal = {key: profile[key] for key in ("name", "nickname", "username") if isinstance(profile.get(key), str)}
    age = _number(profile.get("age"))
    if age is not None and 0 <= age <= 150:
        personal["age"] = age
    if isinstance(profile.get("hobbies"), str):
        personal["hobbies"] = profile["hobbies"]
    elif isinstance(profile.get("hobbies"), list):
        personal["hobbies"] = [value for value in profile["hobbies"] if isinstance(value, str)]
    graded = [review for review in reviews if review["review_sessions"] > 0 and review["last_result"] is not None]
    again_rate = sum(r["last_result"] == "again" for r in graded) / len(graded) if graded else None
    clear_rate = sum(r["last_result"] == "clear" for r in graded) / len(graded) if graded else None
    style = "insufficient_data" if not graded else "needs_examples" if again_rate >= .4 else "steady"
    exported_at = _time(now) if now is not None else datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION, "exported_at": exported_at,
            "producer": {"name": "Echo", "version": APP_VERSION},
            "learner": {"local_id": _id("learner", profile_created) if profile_created else None, "profile": personal},
            "coverage": {"scope": "saved_history_only", "retained_lessons": len(lessons),
                         "lesson_storage_limit": 50, "active_lesson_included": False,
                         "per_question_history_available": False},
            "summary": {"knowledge_count": len(knowledge), "review_record_count": len(reviews),
                        "strength_ids": [p["id"] for p in knowledge if p["state"] == "strength"],
                        "weakness_ids": [p["id"] for p in knowledge if p["state"] == "weakness"],
                        "developing_ids": [p["id"] for p in knowledge if p["state"] == "developing"]},
            "learning_preferences": {"style": style, "sample_topics": len(graded), "again_rate": again_rate,
                                     "clear_rate": clear_rate, "source": "latest_review_self_reports"},
            "knowledge_points": knowledge, "recurring_difficulties": recurring,
            "reviews": reviews, "lessons": lessons,
            "methodology": {"version": "1.0.0", "mastery_is_exam_score": False,
                            "states_are": "rule_based_indicators_not_ability_certification",
                            "repeat_count_is": "distinct_saved_lessons_with_difficulty",
                            "subject_source": "course_title_prefix", "missing_values": "null"},
            "excluded": ["api_keys", "provider_configuration", "raw_audio", "screenshots", "avatar", "imported_documents", "html_code"],
            "warnings": warnings}


def build_export(now=None, sections=None):
    """Export selected personal indicators, never the per-lesson history."""
    chosen = set(SECTIONS if sections is None else sections)
    if not chosen or chosen - set(SECTIONS):
        raise ValueError("请至少选择一个有效的个人数据项。")
    snapshot = _build_evidence_snapshot(now)
    points = []
    for point in snapshot["knowledge_points"]:
        points.append({key: point[key] for key in ("id", "topic", "subject", "state", "reasons", "latest_mastery")}
                      | {"learning_sessions": len({o["lesson_id"] for o in point["observations"]}),
                         "difficulty_sessions": len(point["difficulty_lesson_ids"])})
    data = {key: snapshot[key] for key in ("format", "exported_at", "producer", "methodology", "warnings")}
    data.update(schema_version=SCHEMA_VERSION, selected_sections=[s for s in SECTIONS if s in chosen],
                coverage={"scope": "personal_aggregate", "saved_lesson_count": len(snapshot["lessons"]),
                          "lesson_storage_limit": 50, "active_lesson_included": False,
                          "per_question_history_available": False, "lesson_details_included": False})
    data["excluded"] = snapshot["excluded"] + ["lesson_details", "lesson_summaries", "lesson_ids"]
    if "profile" in chosen:
        data["learner"] = snapshot["learner"]
    if "mastery" in chosen:
        data["knowledge_points"] = points
    if "difficulties" in chosen:
        data["difficulties"] = {
            "weaknesses": [p for p in points if p["state"] == "weakness"],
            "recurring": [{key: item[key] for key in ("knowledge_id", "topic", "affected_lesson_count", "basis")}
                          for item in snapshot["recurring_difficulties"]]}
    if "reviews" in chosen:
        data["reviews"] = snapshot["reviews"]
    if "preferences" in chosen:
        data["learning_preferences"] = snapshot["learning_preferences"]
    return data


def export_json(destination, sections=None):
    target = Path(destination).expanduser().resolve()
    # A save dialog may point anywhere; prevent overwriting Echo's own live files.
    private_names = {"profile.json", "review.json", "lessons.json", "knowledge.json", "mindmap.json", ".env", ".env.example"}
    if target.parent == Path(paths.config_dir()).resolve() and target.name.lower() in private_names:
        raise ValueError("请选择新的导出文件名，不能覆盖 Echo 正在使用的数据文件。")
    data = build_export(sections=sections)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".echo-export-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return data
