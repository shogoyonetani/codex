#!/usr/bin/env python3
"""Generate ACF local JSON + PHP template from annotated HTML.

Usage:
  python html_to_acf_tool.py input.html --group-title "Page Fields"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SELF_CLOSING = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Node:
    tag: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List["Node"] = field(default_factory=list)
    text: Optional[str] = None

    @property
    def is_text(self) -> bool:
        return self.tag is None


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="__root__")
        self.stack: List[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in SELF_CLOSING:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(Node(text=data))


def slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "field"


def infer_type(node: Node) -> str:
    explicit = node.attrs.get("data-acf-type", "").strip().lower()
    if explicit:
        return explicit
    if node.tag == "img":
        return "image"
    if node.tag == "a":
        return "url"
    if node.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "span", "li", "strong", "em"}:
        return "text"
    return "textarea"


def field_def(name: str, ftype: str, label: Optional[str] = None, sub_fields: Optional[List[dict]] = None) -> dict:
    base = {
        "key": f"field_{name}",
        "label": label or name.replace("_", " ").title(),
        "name": name,
        "type": ftype,
    }
    if ftype == "repeater":
        base["layout"] = "block"
        base["button_label"] = "Add Row"
        base["sub_fields"] = sub_fields or []
    return base


def render_attrs(attrs: Dict[str, str], skip: Iterable[str] = ()) -> str:
    ignored = set(skip)
    out: List[str] = []
    for k, v in attrs.items():
        if k in ignored or k.startswith("data-acf"):
            continue
        out.append(f' {k}="{v}"')
    return "".join(out)


def field_expr(name: str, ftype: str, in_repeater: bool) -> str:
    fn = "get_sub_field" if in_repeater else "get_field"
    if ftype in {"text", "textarea", "email", "number"}:
        return f"<?php echo esc_html({fn}('{name}')); ?>"
    if ftype in {"url"}:
        return f"<?php echo esc_url({fn}('{name}')); ?>"
    if ftype in {"link"}:
        return f"<?php echo esc_url({fn}('{name}')['url']); ?>"
    if ftype in {"image"}:
        return f"<?php echo esc_url(wp_get_attachment_image_url({fn}('{name}'), 'full')); ?>"
    if ftype in {"wysiwyg"}:
        the_fn = "the_sub_field" if in_repeater else "the_field"
        return f"<?php {the_fn}('{name}'); ?>"
    return f"<?php echo esc_html({fn}('{name}')); ?>"


def collect_fields(node: Node, parent_repeater: Optional[str] = None) -> List[dict]:
    fields: List[dict] = []
    for ch in node.children:
        if ch.is_text:
            continue
        rep = ch.attrs.get("data-acf-repeater")
        if rep:
            rep_name = slug(rep)
            sub = collect_fields(ch)
            fields.append(field_def(rep_name, "repeater", ch.attrs.get("data-acf-label"), sub_fields=sub))
            continue
        fname = ch.attrs.get("data-acf-field")
        if fname:
            n = slug(fname)
            fields.append(field_def(n, infer_type(ch), ch.attrs.get("data-acf-label")))
        fields.extend(collect_fields(ch, parent_repeater))

    seen = set()
    unique: List[dict] = []
    for f in fields:
        key = f["name"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def render_node(node: Node, in_repeater: bool = False) -> str:
    if node.is_text:
        return node.text or ""

    rep = node.attrs.get("data-acf-repeater")
    if rep:
        name = slug(rep)
        attrs = render_attrs(node.attrs)
        inner = "".join(render_node(c, in_repeater=True) for c in node.children)
        return (
            f"<?php if (have_rows('{name}')): ?>\n"
            f"<?php while (have_rows('{name}')): the_row(); ?>\n"
            f"<{node.tag}{attrs}>{inner}</{node.tag}>\n"
            f"<?php endwhile; ?>\n"
            f"<?php endif; ?>"
        )

    fname = node.attrs.get("data-acf-field")
    if fname:
        name = slug(fname)
        ftype = infer_type(node)
        attrs = dict(node.attrs)
        if node.tag == "img":
            attrs["src"] = field_expr(name, "image", in_repeater)
            alt_name = slug(f"{name}_alt")
            attrs["alt"] = f"<?php echo esc_attr({('get_sub_field' if in_repeater else 'get_field')}('{alt_name}')); ?>"
            attr_str = render_attrs(attrs)
            return f"<{node.tag}{attr_str}>"
        if node.tag == "a":
            attrs["href"] = field_expr(name, ftype, in_repeater)
            attr_str = render_attrs(attrs)
            inner = "".join(render_node(c, in_repeater=in_repeater) for c in node.children).strip() or field_expr(name, "text", in_repeater)
            return f"<{node.tag}{attr_str}>{inner}</{node.tag}>"

        attr_str = render_attrs(attrs)
        content = field_expr(name, ftype, in_repeater)
        return f"<{node.tag}{attr_str}>{content}</{node.tag}>"

    attr_str = render_attrs(node.attrs)
    inner = "".join(render_node(c, in_repeater=in_repeater) for c in node.children)
    if node.tag in SELF_CLOSING:
        return f"<{node.tag}{attr_str}>"
    return f"<{node.tag}{attr_str}>{inner}</{node.tag}>"


def build_group(title: str, group_key: str, fields: List[dict], location_param: str = "page") -> dict:
    return {
        "key": group_key,
        "title": title,
        "fields": fields,
        "location": [[{"param": "post_type", "operator": "==", "value": location_param}]],
        "menu_order": 0,
        "position": "normal",
        "style": "default",
        "label_placement": "top",
        "instruction_placement": "label",
        "hide_on_screen": "",
        "active": True,
        "description": "Generated by html_to_acf_tool.py",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Annotated HTML -> ACF JSON + PHP generator")
    ap.add_argument("input", type=Path, help="Input HTML file")
    ap.add_argument("--group-title", default="Generated Fields")
    ap.add_argument("--group-key", default="group_generated_fields")
    ap.add_argument("--post-type", default="page")
    ap.add_argument("--json-out", type=Path, default=Path("acf-group.json"))
    ap.add_argument("--php-out", type=Path, default=Path("template-generated.php"))
    args = ap.parse_args()

    html = args.input.read_text(encoding="utf-8")
    p = TreeParser()
    p.feed(html)

    fields = collect_fields(p.root)

    # For image fields, auto add an optional alt text field to improve accessibility.
    image_fields = [f for f in fields if f.get("type") == "image"]
    for img in image_fields:
        alt_name = f"{img['name']}_alt"
        if all(f["name"] != alt_name for f in fields):
            fields.append(field_def(alt_name, "text", label=f"{img['label']} Alt"))

    group = build_group(args.group_title, args.group_key, fields, args.post_type)
    args.json_out.write_text(json.dumps([group], ensure_ascii=False, indent=2), encoding="utf-8")

    body = "".join(render_node(ch) for ch in p.root.children)
    php = (
        "<?php\n"
        "/*\n"
        " * Generated template fragment from annotated HTML\n"
        " */\n"
        "?>\n"
        f"{body}\n"
    )
    args.php_out.write_text(php, encoding="utf-8")

    print(f"Generated: {args.json_out}")
    print(f"Generated: {args.php_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
