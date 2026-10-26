# METADATA
# title: ci_dispatch
# description: The gate is dispatched on a head only when it is dispatchable and has no run there.
package runs.ci_dispatch

import rego.v1

_request := input.ci_dispatch

_gate_runs contains run if {
	some run in _request.runs
	run.path == _request.workflow
}

_unobserved contains field if {
	some field in ["triggers", "runs"]
	_request[field] == null
}

# METADATA
# title: The dispatch request is supplied, never assumed
# custom:
#   code: ERR_CI_DISPATCH_INPUT_MISSING
deny contains denial if {
	not input.ci_dispatch
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no ci_dispatch input: an absent observation would read as cleared to dispatch",
	}
}

# METADATA
# title: There is a pull request to dispatch on
# custom:
#   code: ERR_CI_DISPATCH_NO_PR
deny contains denial if {
	_request.pr == null
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the branch has no open pull request",
	}
}

# METADATA
# title: Every state a dispatch depends on was read
# custom:
#   code: ERR_CI_DISPATCH_UNOBSERVED
deny contains denial if {
	count(_unobserved) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v could not be read: a dispatch is never decided unread", [_unobserved]),
	}
}

# METADATA
# title: The gate workflow declares a workflow_dispatch trigger
# custom:
#   code: ERR_CI_DISPATCH_NOT_DISPATCHABLE
deny contains denial if {
	_request.triggers != null
	not "workflow_dispatch" in _request.triggers
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v has no workflow_dispatch trigger: GitHub would refuse it", [_request.workflow]),
	}
}

# METADATA
# title: The gate has no run on the head yet
# custom:
#   code: ERR_CI_DISPATCH_RUN_EXISTS
deny contains denial if {
	count(_gate_runs) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v already has a run on the head, so nothing is dispatched", [_request.workflow]),
	}
}
