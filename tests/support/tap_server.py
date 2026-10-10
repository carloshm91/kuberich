"""Actual owned Git object/branch operations behind a loopback tap API."""

import base64
import json
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit

from scripts.homebrew import TAP
from tests.support.release_server import ReleaseServer


class TapServer(ReleaseServer):
    def __init__(self, directory):
        super().__init__(directory)
        self.command("update-ref", "refs/heads/main", self.sha)
        self.pulls = []
        self.fail_pull = False
        self.private = False
        self.owner = {"login": "kuberich", "type": "Organization"}

    def get(self, path):
        parsed = urlsplit(path)
        route = unquote(parsed.path)
        prefix = f"/repos/{TAP}"
        if route == prefix:
            return {
                "full_name": TAP,
                "private": self.private,
                "default_branch": "main",
                "owner": self.owner,
            }
        if route.startswith(prefix + "/contents/"):
            ref = parse_qs(parsed.query)["ref"][0]
            file = route.removeprefix(prefix + "/contents/")
            try:
                content = self.command("show", ref + ":" + file)
            except subprocess.CalledProcessError:
                return None
            return {"content": base64.encodebytes(content.encode()).decode()}
        if route.startswith(prefix + "/git/ref/heads/"):
            ref = "refs/heads/" + route.removeprefix(prefix + "/git/ref/heads/")
            try:
                sha = self.command("rev-parse", "--verify", ref).strip()
            except subprocess.CalledProcessError:
                return None
            return {"object": {"sha": sha}}
        if route.startswith(prefix + "/git/commits/"):
            sha = route.rsplit("/", 1)[1]
            return {"tree": {"sha": self.command("show", "--format=%T", "--no-patch", sha).strip()}}
        if route == prefix + "/pulls":
            return self.pulls
        return super().get(path)

    def post(self, path, body, content_type):
        self.posts.append((path, body))
        value = json.loads(body)
        prefix = f"/repos/{TAP}"
        if path == prefix + "/git/blobs":
            assert value["encoding"] == "utf-8"
            return 201, {
                "sha": self.command("hash-object", "-w", "--stdin", input=value["content"]).strip()
            }
        if path == prefix + "/git/trees":
            self.command("read-tree", value["base_tree"])
            for entry in value["tree"]:
                assert entry["mode"] == "100644" and entry["type"] == "blob"
                self.command(
                    "update-index", "--add", "--cacheinfo", "100644", entry["sha"], entry["path"]
                )
            return 201, {"sha": self.command("write-tree").strip()}
        if path == prefix + "/git/commits":
            assert value["author"]["email"] == "carloshm91@gmail.com"
            assert len(value["parents"]) == 1
            sha = self.command(
                "-c",
                "user.name=Tap Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit-tree",
                value["tree"],
                "-p",
                value["parents"][0],
                "-m",
                value["message"],
            ).strip()
            return 201, {"sha": sha}
        if path == prefix + "/git/refs":
            try:
                self.command("update-ref", value["ref"], value["sha"], "0" * 40)
            except subprocess.CalledProcessError:
                return 422, {"message": "ref exists"}
            return 201, value
        if path == prefix + "/pulls":
            if self.fail_pull:
                return 503, {"message": "owned transient failure after immutable branch creation"}
            self.pulls.append({**value, "html_url": "https://github.com/owned-fixture/pull/1"})
            return 201, self.pulls[-1]
        return 404, {}
