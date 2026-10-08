from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ControlRecord:
    selector: str
    tag: str
    text: str
    href: str | None = None
    role: str | None = None
    control_type: str = "unknown"
    is_safe: bool = True
    unsafe_reason: str | None = None
    outcome: str | None = None
    destination_url: str | None = None
    target_state_id: str | None = None
    error_message: str | None = None


@dataclass
class State:
    id: str
    url: str
    fingerprint_hash: str
    title: str = ""
    depth: int = 0
    screenshot_filename: str | None = None
    screenshot_derivative: str | None = None
    controls: list[ControlRecord] = field(default_factory=list)
    has_iframes: bool = False


@dataclass
class Transition:
    source_state_id: str
    target_state_id: str
    control_selector: str
    control_text: str
    is_tree_edge: bool = True


@dataclass
class Graph:
    states: dict[str, State] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    root_state_id: str | None = None
    termination_reason: str | None = None
    out_of_scope_urls: list[dict] = field(default_factory=list)
    config_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    _fingerprint_index: dict[tuple[str, str], str] = field(
        default_factory=dict, repr=False, compare=False
    )
    _next_state_num: int = field(default=0, repr=False, compare=False)

    def add_state(
        self,
        url: str,
        fingerprint_hash: str,
        title: str = "",
        depth: int = 0,
    ) -> State:
        state_id = f"s{self._next_state_num}"
        self._next_state_num += 1

        state = State(
            id=state_id,
            url=url,
            fingerprint_hash=fingerprint_hash,
            title=title,
            depth=depth,
        )
        self.states[state_id] = state
        self._fingerprint_index[(url, fingerprint_hash)] = state_id

        if self.root_state_id is None:
            self.root_state_id = state_id

        return state

    def find_state_by_fingerprint(self, url: str, dom_hash: str) -> State | None:
        state_id = self._fingerprint_index.get((url, dom_hash))
        if state_id is not None:
            return self.states.get(state_id)
        return None

    def add_transition(
        self,
        source_state_id: str,
        target_state_id: str,
        control_selector: str,
        control_text: str,
        is_tree_edge: bool = True,
    ) -> Transition:
        t = Transition(
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            control_selector=control_selector,
            control_text=control_text,
            is_tree_edge=is_tree_edge,
        )
        self.transitions.append(t)
        return t

    def add_out_of_scope(self, source_state_id: str, url: str, control_text: str = "") -> None:
        self.out_of_scope_urls.append(
            {"source_state_id": source_state_id, "url": url, "control_text": control_text}
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        data = asdict(self)
        data.pop("_fingerprint_index", None)
        data.pop("_next_state_num", None)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> Graph:
        path = Path(path)
        data = json.loads(path.read_text())

        graph = cls()
        graph.root_state_id = data.get("root_state_id")
        graph.termination_reason = data.get("termination_reason")
        graph.out_of_scope_urls = data.get("out_of_scope_urls", [])
        graph.config_path = data.get("config_path")
        graph.started_at = data.get("started_at")
        graph.finished_at = data.get("finished_at")

        for state_id, state_data in data.get("states", {}).items():
            controls = [ControlRecord(**c) for c in state_data.get("controls", [])]
            state = State(
                id=state_data["id"],
                url=state_data["url"],
                fingerprint_hash=state_data["fingerprint_hash"],
                title=state_data.get("title", ""),
                depth=state_data.get("depth", 0),
                screenshot_filename=state_data.get("screenshot_filename"),
                screenshot_derivative=state_data.get("screenshot_derivative"),
                controls=controls,
                has_iframes=state_data.get("has_iframes", False),
            )
            graph.states[state_id] = state
            graph._fingerprint_index[(state.url, state.fingerprint_hash)] = state_id
            num = int(state_id[1:])
            if num >= graph._next_state_num:
                graph._next_state_num = num + 1

        for t_data in data.get("transitions", []):
            graph.transitions.append(Transition(**t_data))

        return graph

    @property
    def state_count(self) -> int:
        return len(self.states)

    @property
    def transition_count(self) -> int:
        return len(self.transitions)

    @property
    def tree_edge_count(self) -> int:
        return sum(1 for t in self.transitions if t.is_tree_edge)

    @property
    def cross_link_count(self) -> int:
        return sum(1 for t in self.transitions if not t.is_tree_edge)
