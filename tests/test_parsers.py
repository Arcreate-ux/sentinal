import pytest
from pydantic import ValidationError
from sentinel.bot.parsers import MessageParser
from sentinel.bot.schemas import PerformanceReport

class DummyAIEngine:
    async def call(self, **kwargs):
        # We can mock this for AI tests if needed, but for now we focus on regex & validation
        return '{"attempted": 20, "correct": 15, "time_taken": 40, "is_report": true}'

@pytest.fixture
def parser():
    return MessageParser(DummyAIEngine())

def test_try_regex_performance_structured(parser):
    text = "A=15 C=12 T=50"
    result = parser._try_regex_performance(text)
    assert result is not None
    assert result.attempted == 15
    assert result.correct == 12
    assert result.time_taken == 50
    assert result.is_report is True

def test_try_regex_performance_natural(parser):
    text = "I did 15 and got 12 right in 50 mins for Physics Ex 1A"
    result = parser._try_regex_performance(text)
    assert result is not None
    assert result.attempted == 15
    assert result.correct == 12
    assert result.time_taken == 50
    assert result.subject == "Physics"

def test_try_regex_performance_compact(parser):
    text = "15/12/50"
    result = parser._try_regex_performance(text)
    assert result is not None
    assert result.attempted == 15
    assert result.correct == 12
    assert result.time_taken == 50

def test_pydantic_schema_validation():
    # Valid
    raw_valid = '{"attempted": 20, "correct": 15, "time_taken": 40, "is_report": true}'
    report = PerformanceReport.model_validate_json(raw_valid)
    assert report.attempted == 20

    # Invalid types (Pydantic should coerce or fail)
    # E.g., time_taken provided as a string that can be coerced
    raw_coercible = '{"attempted": "20", "correct": "15", "time_taken": "40", "is_report": true}'
    report = PerformanceReport.model_validate_json(raw_coercible)
    assert report.attempted == 20

    # Missing required field
    raw_invalid = '{"attempted": 20, "correct": 15, "is_report": true}'
    with pytest.raises(ValidationError):
        PerformanceReport.model_validate_json(raw_invalid)

@pytest.mark.asyncio
async def test_parse_homework(parser):
    text = "Physics Ch.5 Ex2A Q1-20"
    results = await parser.parse_homework(text)
    assert len(results) == 1
    assert results[0].subject == "Physics"
    assert results[0].questions == 20

@pytest.mark.asyncio
async def test_parse_test_scores(parser):
    text = "Physics 45/120, Chem 62/120, Maths 55/120"
    result = await parser.parse_test_scores(text)
    assert result.p_score == 45
    assert result.c_score == 62
    assert result.m_score == 55
