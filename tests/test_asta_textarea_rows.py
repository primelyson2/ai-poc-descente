from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FormContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.labels = {}
        self.textareas = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "label" and values.get("for"):
            self.labels[values["for"]] = values
        if tag == "textarea" and values.get("id"):
            self.textareas[values["id"]] = values


def _view_source() -> str:
    return (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")


def _form_contract() -> FormContractParser:
    source = _view_source()
    start = source.index('<section class="tuning-shell">')
    end = source.index("</section>`;", start)
    parser = FormContractParser()
    parser.feed(source[start:end])
    return parser


def test_main_sql_and_llm_notes_have_exact_rows_and_explicit_labels():
    form = _form_contract()

    assert form.textareas["asta-sql"]["rows"] == "10"
    assert form.textareas["asta-tuning-notes"]["rows"] == "3"
    assert form.labels["asta-sql"]["for"] == "asta-sql"
    assert form.labels["asta-tuning-notes"]["for"] == "asta-tuning-notes"


def test_rows_control_height_only_for_the_two_visible_input_textareas():
    source = _view_source()
    marker = "/* Visible ASTA inputs: let the rows attribute control initial height. */"
    start = source.index(marker)
    end = source.index("@media", start)
    scoped_css = source[start:end]

    assert "#asta-sql" in scoped_css
    assert "#asta-tuning-notes" in scoped_css
    assert "height:auto" in scoped_css
    assert "min-height:0" in scoped_css
    assert "overflow-y:auto" in scoped_css
    assert "asta-sql-only-llm" not in scoped_css
    assert "tuning-report-code" not in scoped_css
