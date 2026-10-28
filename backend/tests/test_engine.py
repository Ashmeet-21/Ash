from datetime import date

from app.engine.eligibility import check_all
from app.engine.extract import extract
from app.engine.scorer import score
from app.engine.skills import get_taxonomy
from app.engine.tailor import clean_role, fill_template, tailor
from app.engine.validator import validate_objective, validate_tailored, validate_text_rules
from app.facts import render_resume_text
from tests.conftest import FIXTURES


# ---------------------------------------------------------------- skills

def test_aliases_and_boundaries():
    tax = get_taxonomy()
    found = tax.find("Experience with JS, k8s, Postgres and C++; JavaScript not Java. Node.js and C#.")
    assert found["JavaScript"] == 2
    assert found["Kubernetes"] == 1
    assert found["PostgreSQL"] == 1
    assert found["C++"] == 1
    assert found["Java"] == 1
    assert found["Node.js"] == 1
    assert found["C#"] == 1
    assert "SQL" not in found  # must not match inside PostgreSQL


def test_ambiguous_words_do_not_match():
    tax = get_taxonomy()
    found = tax.find("For the rest of the spring term, go ahead and render the agents in testing. In-person work helps spark innovation.")
    assert not {"REST APIs", "Spring Boot", "Go", "Render", "AI agents", "Unit testing", "Spark"} & set(found)


def test_canonical():
    tax = get_taxonomy()
    assert tax.canonical("k8s") == "Kubernetes"
    assert tax.canonical("Golang") == "Go"
    assert tax.canonical("not a skill") is None


# ---------------------------------------------------------------- extraction

def test_extract_required_vs_preferred(soc_jd):
    ex = extract(soc_jd, title="Junior SOC Analyst", use_llm=False)
    req = {r.item: r.required for r in ex.requirements if r.kind == "hard"}
    assert req["SIEM"] and req["MITRE ATT&CK"] and req["Incident response"] and req["Linux"]
    assert req["AWS"] is False and req["Docker"] is False and req["Security+"] is False
    assert ex.min_years == 0
    assert ex.education == {"required": True, "level": "bachelor", "fields": ["computer science", "cybersecurity"]}
    assert ex.salary == {"min": 60000, "max": 72000, "currency": "CAD"}
    assert ex.seniority == "junior"
    assert ex.location.startswith("Vancouver")


def test_extract_years_and_senior():
    ex = extract((FIXTURES / "senior_java.txt").read_text(), title="Senior Backend Engineer (Java)", use_llm=False)
    assert ex.min_years == 6
    assert ex.seniority == "senior"
    assert ex.education["level"] == "master"


# ---------------------------------------------------------------- scoring

def test_score_good_vs_bad_fit(facts, soc_jd):
    base = render_resume_text(facts)
    good = score(extract(soc_jd, title="Junior SOC Analyst", use_llm=False), base, soc_jd, facts)
    bad_jd = (FIXTURES / "senior_java.txt").read_text()
    bad = score(extract(bad_jd, title="Senior Backend Engineer (Java)", use_llm=False), base, bad_jd, facts)
    assert 0 <= bad.total < good.total <= 100
    assert good.total > 55
    assert bad.total < 40


def test_score_breakdown_weights_sum(facts, soc_jd):
    s = score(extract(soc_jd, use_llm=False), render_resume_text(facts), soc_jd, facts)
    assert sum(c.weight for c in s.components) == 100


def test_keyword_stuffing_does_not_help(facts, soc_jd):
    ex = extract(soc_jd, use_llm=False)
    base = render_resume_text(facts)
    stuffed = base + "\n" + " ".join(["SIEM Linux MITRE ATT&CK"] * 30)
    a = next(c for c in score(ex, base, soc_jd, facts).components if c.key == "keywords")
    b = next(c for c in score(ex, stuffed, soc_jd, facts).components if c.key == "keywords")
    # Extra copies of terms already present are capped.
    assert b.value - a.value < 0.15


def test_gap_classification(facts, soc_jd):
    s = score(extract(soc_jd, use_llm=False), render_resume_text(facts), soc_jd, facts)
    status = {g.item: g.status for g in s.gaps}
    assert status["SIEM"] == "shown"
    assert status["Incident response"] == "hidden"  # in pool, not on the resume
    assert status["Splunk"] == "adjacent"  # same family as SIEM/Wazuh
    assert status["AWS"] == "gap"
    adj = next(g for g in s.gaps if g.item == "Splunk")
    assert "LogSentry" in adj.evidence


def test_education_not_counted_when_not_asked(facts):
    jd = "Software Developer\nRequirements:\n- Python and FastAPI\n- Docker\n"
    s = score(extract(jd, use_llm=False), render_resume_text(facts), jd, facts)
    edu = next(c for c in s.components if c.key == "education")
    assert edu.value is None


# ---------------------------------------------------------------- eligibility

def _flags(text, facts, title=""):
    ex = extract(text, title=title, use_llm=False)
    return {f.type: f for f in check_all(text, ex, facts, today=date(2026, 10, 1))}


def test_flags_coop(facts):
    flags = _flags((FIXTURES / "coop_ai.txt").read_text(), facts, title="AI Engineering Co-op (Summer 2027)")
    assert flags["grad_window"].severity == "block"  # window Dec 2027 to Jun 2028 excludes May 2027
    assert flags["term_length"].severity == "block"  # 12 months > 8
    assert flags["enrollment"].severity == "info"


def test_flags_senior_french(facts):
    flags = _flags((FIXTURES / "senior_java.txt").read_text(), facts, title="Senior Backend Engineer (Java)")
    assert flags["language"].severity == "block"
    assert flags["years_required"].severity == "block"
    assert flags["education"].severity == "block"
    assert flags["location"].severity in ("warn", "block")
    assert flags["seniority"].severity == "warn"


def test_flags_sponsorship_by_region(facts):
    vancouver = _flags("Analyst\nLocation: Vancouver, BC\nWe do not offer visa sponsorship.", facts, title="Analyst")
    dubai = _flags("Analyst\nLocation: Dubai, UAE\nWe do not offer visa sponsorship.", facts, title="Analyst")
    assert vancouver["sponsorship"].severity == "info"
    assert dubai["sponsorship"].severity == "block"  # example profile needs sponsorship in Dubai


def test_flags_grad_class(facts):
    assert _flags("New Grad Engineer\nOpen to the Class of 2026 only.", facts)["grad_window"].severity == "block"
    assert "grad_window" not in _flags("New Grad Engineer\nOpen to the Class of 2027.", facts)


def test_missing_info_flags(facts):
    flags = _flags("Developer\nWe need Python.", facts)
    assert {"missing_company", "missing_salary", "missing_location"} <= set(flags)


# ---------------------------------------------------------------- validator

def test_master_resume_passes(facts):
    assert validate_tailored(facts.resume.objective, facts.resume.skills, facts).ok


def test_validator_rejects_em_dash_gpa_learning():
    res = validate_text_rules("Built X — fast. CGPA 3.9. Rust (learning)")
    assert {i.rule for i in res.errors} == {"em_dash", "no_cgpa", "no_learning_tag"}


def test_validator_rejects_unlisted_skill_and_overclaim(facts):
    obj = fill_template(facts.resume.objective_template, "Backend Developer", ["backend APIs", "cloud infrastructure"],
                        ["Python", "Kubernetes", "FastAPI", "PostgreSQL", "Docker", "Linux", "Git", "SQL"])
    rules = {i.rule for i in validate_objective(obj, facts).errors}
    assert "objective_unlisted_skill" in rules
    obj2 = obj.replace("Kubernetes", "Bash").replace("hands-on project experience", "production experience")
    assert "objective_template" in {i.rule for i in validate_objective(obj2, facts).errors}


def test_validator_rejects_changed_locked_bullet(facts):
    from app.engine.validator import validate_document

    text = render_resume_text(facts).replace("2,000+ daily events", "5,000+ daily events")
    assert "locked_bullet" in {i.rule for i in validate_document(text, facts).errors}


def test_validator_rejects_skill_outside_pool(facts):
    skills = {k: list(v) for k, v in facts.resume.skills.items()}
    skills["Languages"].append("Rust")
    assert "skills_unlisted" in {i.rule for i in validate_tailored(facts.resume.objective, skills, facts).errors}


# ---------------------------------------------------------------- tailor

def test_clean_role():
    assert clean_role("Junior SOC Analyst (Hybrid) - Vancouver") == "SOC Analyst"
    assert clean_role("Software Engineer, New Grad 2027") == "Software Engineer"


def test_tailor_template_is_valid_and_improves_score(facts, soc_jd):
    ex = extract(soc_jd, title="Junior SOC Analyst", use_llm=False)
    t = tailor(ex, soc_jd, facts, use_llm=False)
    assert t.validation.ok, t.validation.to_dict()
    assert t.source == "template"
    assert 8 <= len(t.tools) <= 10
    assert 2 <= len(t.areas) <= 3
    pool = facts.pool_names()
    assert all(i in pool for items in t.skills.values() for i in items)
    assert "Incident response" in [i for items in t.skills.values() for i in items]  # hidden skill surfaced
    before = score(ex, render_resume_text(facts), soc_jd, facts).total
    after = score(ex, render_resume_text(facts, t.objective, t.skills), soc_jd, facts).total
    assert after > before


def test_tailor_never_adds_true_gaps(facts):
    jd = (FIXTURES / "senior_java.txt").read_text()
    ex = extract(jd, title="Senior Backend Engineer (Java)", use_llm=False)
    t = tailor(ex, jd, facts, use_llm=False)
    text = t.objective + " " + " ".join(i for items in t.skills.values() for i in items)
    for gap in ("Java", "Kafka", "Kubernetes", "AWS", "Spring Boot"):
        assert gap not in get_taxonomy().find(text)
    assert t.validation.ok


def test_role_drops_skills_you_lack(facts):
    assert clean_role("Senior Java Engineer", facts) == "Software Engineer"
    assert clean_role("Spring Boot Backend Developer", facts) == "Backend Developer"
    assert clean_role("Python Developer", facts) == "Python Developer"  # in the pool, so kept
    assert clean_role("iOS Engineer, Government Products", facts) == "Software Engineer"
    jd = (FIXTURES / "senior_java.txt").read_text()
    t = tailor(extract(jd, title="Senior Java Engineer", use_llm=False), jd, facts, use_llm=False)
    assert "Java" not in get_taxonomy().find(t.objective)
    assert t.validation.ok, t.validation.to_dict()


def test_validator_rejects_unlisted_skill_in_role(facts):
    objective = fill_template(facts.resume.objective_template, "Java Engineer", ["backend APIs", "threat detection"], ["Python", "FastAPI"])
    errors = validate_objective(objective, facts).errors
    assert any(e.rule == "objective_role_skill" for e in errors)


def test_an_article():
    assert "seeking an AI Engineer role" in fill_template("seeking a {role} role in {areas} using {tools}.", "AI Engineer", ["x", "y"], ["a", "b"])
