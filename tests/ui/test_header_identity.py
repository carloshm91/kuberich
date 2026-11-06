"""Long owned identities remain visible without losing table scope or UID navigation."""

import copy
import json
import logging
from pathlib import Path

import pytest
import yaml

from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.authorization import AuthorizationMode
from kuberich.domain.connections import ConnectionRequest
from kuberich.ui.app import KubeRichApp
from tests.support.authorization_ui import ROLES, RULE, AuthorizationAPI, authorization_api
from tests.support.workspace import wait_for
from tests.ui.test_authorization import ready as auth_ready
from tests.ui.test_relationship_navigation import RelationshipAPI, graph_ready

OUT = Path("artifacts/issue75/terminal-review/header-green")
CONTEXT = "synthetic-context-" + "unbroken-label-" * 7 + "identity"
CLUSTER = "synthetic-cluster-" + "unbroken-label-" * 7 + "identity"
USER = "synthetic-user-" + "unbroken-label-" * 7 + "identity"
NS = "synthetic-observability-review-team"
ROLE = "owned-resource-reader-with-a-long-synthetic-name"


class ReviewAPI(AuthorizationAPI):
    def __init__(self):
        super().__init__()
        self.relation = RelationshipAPI()
        for (group, version, plural, namespace, name), body in self.relation.objects.items():
            if version == "v1":
                self.objects[group, plural, namespace, name] = copy.deepcopy(body)
        for key, body in tuple(self.objects.items()):
            if key[2] == "team":
                del self.objects[key]
                body["metadata"]["namespace"] = NS
                self.objects[(*key[:2], NS, key[3])] = body
        del self.objects["rbac.authorization.k8s.io", "roles", NS, "reader"]
        self.add(ROLES, ROLE, namespace=NS, rules=[RULE, dict(RULE, verbs=["watch"])])

    def roots(self):
        base = super().roots()
        extra = self.relation.roots()
        for path, body in extra.items():
            if path not in base:
                base[path] = copy.deepcopy(body)
        resources = {x["name"]: x for x in base["/api/v1"]["resources"]}
        resources.update({x["name"]: x for x in extra["/api/v1"]["resources"]})
        base["/api/v1"]["resources"] = list(resources.values())
        groups = {x["name"]: x for x in base["/apis"]["groups"]}
        groups.update({x["name"]: x for x in extra["/apis"]["groups"]})
        base["/apis"]["groups"] = list(groups.values())
        return base


def config(directory, url):
    path = directory / "owned-kubeconfig"
    value = {
        "current-context": CONTEXT,
        "contexts": [
            {"name": CONTEXT, "context": {"cluster": CLUSTER, "user": USER, "namespace": NS}}
        ],
        "clusters": [{"name": CLUSTER, "cluster": {"server": url}}],
        "users": [{"name": USER, "user": {"token": "synthetic-review-only"}}],
    }
    path.write_text(yaml.safe_dump(value))
    path.chmod(0o600)
    return path


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(value, indent=2, default=str) + "\n")
    p.chmod(0o600)


async def app_frame(app, label, size):
    table = {
        "pulse": app.pulse_table,
        "relationships": app.relationships_table,
        "authorization": app.authorization_table,
    }[app.state.view_kind]
    await table.wait_for_refresh()
    OUT.mkdir(parents=True, exist_ok=True)
    screenshot = app.export_screenshot()
    screenshot_path = OUT / f"{label}-{size[0]}.svg"
    screenshot_path.write_text(screenshot)
    screenshot_path.chmod(0o600)
    assert "synthetic-context-" in screenshot
    if size[0] >= 70:
        assert "synthetic-cluster-" in screenshot and "synthetic-user-" in screenshot
    labels = {
        name: {
            "content": str(app.query_one("#" + name).content),
            "line": app.query_one("#" + name).render_line(0).text,
            "display": app.query_one("#" + name).display,
            "region": app.query_one("#" + name).region,
        }
        for name in ("context", "cluster", "user")
    }
    return {
        "labels": labels,
        "columns": [(k.value, v.content_width) for k, v in table.columns.items()],
        "row_count": table.row_count,
        "row_heights": [table.get_row_height(r.key) for r in table.ordered_rows],
        "viewport": str(table.capture_viewport()),
        "region": str(table.region),
        "max_scroll_x": table.max_scroll_x,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 36), (100, 30), (40, 12)])
async def test_long_header_values_survive_actual_observability_views_and_svg(tmp_path, size):
    api = ReviewAPI()
    async with authorization_api(api) as url:
        path = config(tmp_path, url)
        catalog = load_catalog(ConnectionRequest(kubeconfig=str(path)), {})
        app = KubeRichApp(
            Settings(read_only=True), logging.Logger("synthetic-terminal-review"), catalog=catalog
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command("pulse")
            await wait_for(
                lambda: app.state.view_kind == "pulse" and "pods:all" in app.pulse_table.rows
            )
            await pilot.pause()
            frames = {"pulse": await app_frame(app, "pulse-fresh", size)}
            await app.run_command("pods")
            await wait_for(lambda: app.resources.row_count == 1 and app.resources.display)
            await app.run_command("xray")
            await graph_ready(app)
            await pilot.pause()
            frames["relationships"] = await app_frame(app, "relationships-fresh", size)
            table = app.relationships_table
            before = table.capture_viewport()
            await pilot.press("end")
            await table.wait_for_refresh()
            assert table.scroll_x > 0 and table.capture_viewport().selected == before.selected
            frames["relationships"]["right_edge_text"] = "\n".join(
                table.render_line(i).text for i in range(table.size.height)
            )
            await pilot.press("home")
            await app.run_command("rbac roles")
            await auth_ready(app, AuthorizationMode.ROLES)
            row = next(
                table_row
                for item in app.authorization_table.ordered_rows
                if (table_row := app.authorization_table.row_at(item.key.value)).object_ref
                is not None
                and table_row.object_ref.name == ROLE
            )
            app.authorization_table.move_cursor(row=app.authorization_table.get_row_index(row.key))
            app.authorization_table.focus()
            role_viewport = app.authorization_table.capture_viewport()
            await pilot.press("enter")
            await auth_ready(app, AuthorizationMode.ROLE)
            await pilot.pause()
            frames["authorization"] = await app_frame(app, "authorization-fresh", size)
            await pilot.press("end")
            await app.authorization_table.wait_for_refresh()
            frames["authorization"]["right_edge_text"] = "\n".join(
                app.authorization_table.render_line(i).text
                for i in range(app.authorization_table.size.height)
            )
            await pilot.press("escape")
            await auth_ready(app, AuthorizationMode.ROLES)
            await app.authorization_table.wait_for_refresh()
            restored = app.authorization_table.capture_viewport()
            assert restored.selected == role_viewport.selected and restored.x == role_viewport.x
            frames["authorization"]["back_role_uid"] = app.authorization_table.row_at(
                app.authorization_table.capture_viewport().selected
            ).object_ref.uid
            save(f"headless-{size[0]}.json", frames)
            for frame in frames.values():
                for field, value in (("context", CONTEXT), ("cluster", CLUSTER), ("user", USER)):
                    label = frame["labels"][field]
                    assert label["content"] == field.title() + ": " + value
                    if field == "context" or size[0] >= 70:
                        assert ("synthetic-" + field + "-") in label["line"]
                        assert "…" in label["line"]
                    else:
                        assert not label["display"]
            assert app.state.context == CONTEXT
            assert (
                frames["authorization"]["back_role_uid"]
                == api.objects["rbac.authorization.k8s.io", "roles", NS, ROLE]["metadata"]["uid"]
            )
    assert api.active_watches == 0
