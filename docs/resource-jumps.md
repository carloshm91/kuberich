# Jump to related resources

A jump opens a related view from the selected row. For example, a jump can go
from a Deployment to its pods, or from a node to the pods running on it. You
define jumps in the preference file. Published 0.1.0 packages do not include
jumps.

## Define a jump

Add a `jumps` section to the preference file shown by `kuberich info`:

```yaml
schema_version: 1
jumps:
  schema_version: 1
  definitions:
    pods:
      description: Pods selected by this Deployment
      source: apps/v1/deployments
      target: v1/pods
      labels: "{{ spec.selector.matchLabels }}"
    node-pods:
      source: v1/nodes
      target: v1/pods
      namespace: "*"
      fields: "spec.nodeName={{ metadata.name }}"
```

Each jump has a name and these fields:

| Field | Meaning |
|---|---|
| `source` | The view where the jump is available, as `VERSION/RESOURCE` or `GROUP/VERSION/RESOURCE`. Core resources omit the group. |
| `target` | The view to open, in the same form. Custom resources work too. |
| `namespace` | Optional. The namespace to open. `*` means all namespaces. Without it, the jump uses the namespace of the selected row, or all namespaces if the row has none. |
| `labels` | Optional. A label filter for the target view. |
| `fields` | Optional. A field filter for the target view. Use `labels` or `fields`, not both. |
| `description` | Optional. Up to 200 characters for your own notes. |

## Templates

`namespace`, `labels` and `fields` can include values from the selected row.
Write the path of a field between `{{` and `}}`:

- `{{ metadata.name }}` reads one value.
- `{{ metadata.labels["app.kubernetes.io/name"] }}` reads a key that contains
  dots or slashes.
- `labels: "{{ spec.selector.matchLabels }}"` turns a whole label map into
  `key=value` pairs.

Templates only read fields. They do not support functions, conditions, indexes
or any code. A value is used only if it fits in a selector: letters, digits,
`.`, `_`, `-` and `/`. If a field is missing, or its value contains other
characters, KubeRich does not open the jump and says why.

Label filters use the same syntax as `label:` in the filter box. Field filters
use the same short list of fields as `field:`, such as `metadata.name`,
`status.phase` and `spec.nodeName`.

## Use a jump

Select a row and type `:jump`. If one jump matches the current view, it opens.
If several match, KubeRich lists their names; type `:jump NAME` to choose.

The target view opens with the filter already in the filter box. Press Escape
to clear it. `:back` returns to the previous view.

The filter runs in KubeRich on the rows it already watches. It does not change
what is read from the cluster.

Run `kuberich config check` to check jump definitions without connecting to a
cluster.
