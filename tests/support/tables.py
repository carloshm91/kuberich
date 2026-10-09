"""Owned custom resource and server Table payloads, without live cluster data."""

import copy

from kuberich.domain.resources import api_resource
from tests.support.resources import collection, descriptor, item


def custom_resource(group="owned.example.test", version="v1", name="widgets", namespaced=True):
    return api_resource(
        group + "/" + version,
        {
            **descriptor(name, kind="Widget", namespaced=namespaced),
            "singularName": "widget",
            "shortNames": ["wdg"],
        },
    )


def custom_item(name="one", namespace="team", uid="owned-one", rv="item-version", version="v1"):
    value = item(name, namespace=namespace, uid=uid)
    value["metadata"]["resourceVersion"] = rv
    value.update({"apiVersion": "owned.example.test/" + version, "kind": "Widget"})
    value["spec"] = {"level": 3, "enabled": True}
    return value


def custom_collection(*objects, rv="collection-version", token=""):
    return {
        **collection(*objects, rv=rv, token=token),
        "apiVersion": "owned.example.test/v1",
        "kind": "WidgetList",
    }


def server_table(*objects, rv="collection-version", token="", headers=True):
    return {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "Table",
        "metadata": {"resourceVersion": rv, "continue": token},
        "columnDefinitions": [
            {"name": "Name", "type": "string", "format": "name", "description": "Resource name"},
            {"name": "Level", "type": "integer"},
            {"name": "Enabled", "type": "boolean"},
        ]
        if headers
        else [],
        "rows": [
            {"cells": [obj["metadata"].get("name", ""), 3, True], "object": copy.deepcopy(obj)}
            for obj in objects
        ],
    }
