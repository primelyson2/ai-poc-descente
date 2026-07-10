import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Node:
    def __init__(self, tag="root", attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children = []

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class TreeParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return


def source() -> str:
    return (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")


def form_tree() -> Node:
    text = source()
    start = text.index('<section class="tuning-shell">')
    end = text.index("</section>`;", start) + len("</section>")
    parser = TreeParser()
    parser.feed(text[start:end])
    return parser.root


def css_rule(text: str, selector: str, start=0) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", text[start:])
    assert match, f"missing CSS rule: {selector}"
    return match.group(1)


def test_report_tablist_is_integrated_in_card_header_without_strong_shadow():
    text = source()
    scroll_rule = css_rule(text, ".tuning-report-scroll")
    header_rule = css_rule(text, ".tuning-report-header")
    tablist_rule = css_rule(text, ".tuning-report-tablist")

    assert "overflow:auto" in scroll_rule
    assert "transform:" not in scroll_rule
    assert "contain:" not in scroll_rule
    assert "background:var(--surface)" in header_rule
    assert "border-bottom:1px solid var(--border)" in header_rule
    assert "box-shadow:" not in header_rule
    assert "background:var(--surface-alt)" in tablist_rule
    assert "box-shadow:" not in tablist_rule

    mobile_start = text.index("@media (max-width: 700px)")
    mobile_end = text.index("@media (max-width: 390px)", mobile_start)
    mobile = text[mobile_start:mobile_end]
    mobile_tablist = css_rule(mobile, ".tuning-report-tablist")
    assert "overflow-x:auto" in mobile_tablist
    assert "flex-wrap:nowrap" in mobile_tablist


def test_three_selects_are_direct_semantic_children_of_one_controls_row_and_textareas_are_outside():
    tree = form_tree()
    wrappers = [
        node for node in tree.descendants()
        if "tuning-controls-row" in node.attrs.get("class", "").split()
    ]
    assert len(wrappers) == 1
    wrapper = wrappers[0]
    direct_labels = [child for child in wrapper.children if child.tag == "label"]
    assert len(direct_labels) == 3

    direct_select_ids = []
    for label in direct_labels:
        selects = [node for node in label.descendants() if node.tag == "select"]
        assert len(selects) == 1
        direct_select_ids.append(selects[0].attrs.get("id"))
    assert direct_select_ids == [
        "asta-ai-profile", "asta-workload-type", "asta-sample-sql"
    ]

    wrapper_textarea_ids = {
        node.attrs.get("id") for node in wrapper.descendants() if node.tag == "textarea"
    }
    assert "asta-tuning-notes" not in wrapper_textarea_ids
    assert "asta-sql" not in wrapper_textarea_ids


def test_controls_row_has_three_column_desktop_grid_and_safe_responsive_fallbacks():
    text = source()
    desktop = css_rule(text, ".tuning-controls-row")
    assert "display:grid" in desktop
    assert "grid-template-columns:" in desktop
    assert "repeat(3, minmax(180px, 1fr))" in desktop
    assert "min-width:0" in desktop

    tablet_start = text.index("@media (max-width: 1100px)")
    tablet_end = text.index("@media (max-width: 720px)", tablet_start)
    tablet = text[tablet_start:tablet_end]
    assert "grid-template-columns:repeat(2, minmax(0, 1fr))" in css_rule(tablet, ".tuning-controls-row")

    mobile_start = text.index("@media (max-width: 720px)")
    mobile_end = text.index("@media (max-width: 390px)", mobile_start)
    mobile = text[mobile_start:mobile_end]
    assert "grid-template-columns:minmax(0, 1fr)" in css_rule(mobile, ".tuning-controls-row")
