# METADATA
# title: ci_state
# description: CI can run on a pull request's head only once a repository workflow started there.
package runs.ci_state

import rego.v1

_state := input.ci_state

_repo_runs contains run if {
	some run in _state.runs
	startswith(run.path, ".github/workflows/")
}

_started contains run.path if {
	some run in _repo_runs
	run.conclusion != "startup_failure"
}

_startup_failed contains run.path if {
	some run in _repo_runs
	run.conclusion == "startup_failure"
}

_restricted if {
	_state.allowed_actions != "all"
}

_restricted if {
	_state.sha_pinning_required == true
}

_registered contains workflow if {
	some workflow in _state.workflows
	startswith(workflow.path, ".github/workflows/")
}

_inactive contains sprintf("%v (%v)", [workflow.path, workflow.state]) if {
	some workflow in _registered
	workflow.state != "active"
}

_unobserved contains field if {
	some field in ["actions_enabled", "runs", "actions_status", "workflows"]
	_state[field] == null
}

# METADATA
# title: The CI state request is supplied, never assumed
# custom:
#   code: ERR_CI_STATE_INPUT_MISSING
deny contains denial if {
	not input.ci_state
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no ci_state input: an absent observation would read as CI able to run",
	}
}

# METADATA
# title: There is a pull request
# custom:
#   code: ERR_CI_STATE_NO_PR
deny contains denial if {
	_state.pr == null
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the branch has no open pull request",
	}
}

# METADATA
# title: Every state CI depends on was read
# custom:
#   code: ERR_CI_STATE_UNOBSERVED
deny contains denial if {
	count(_unobserved) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v could not be read from GitHub: an unread state is never assumed", [_unobserved]),
	}
}

# METADATA
# title: GitHub Actions is enabled for the repository
# custom:
#   code: ERR_CI_STATE_ACTIONS_DISABLED
deny contains denial if {
	_state.actions_enabled == false
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "GitHub Actions is disabled for this repository: no workflow can run",
	}
}

# METADATA
# title: GitHub's Actions service is operational while nothing has started
# custom:
#   code: ERR_CI_STATE_GITHUB_DEGRADED
deny contains denial if {
	_state.actions_status != null
	_state.actions_status != "operational"
	count(_started) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("GitHub Actions reads %v, and no repository workflow started here", [_state.actions_status]),
	}
}

# METADATA
# title: No repository workflow failed at startup
# custom:
#   code: ERR_CI_STATE_STARTUP_FAILURE
deny contains denial if {
	count(_startup_failed) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v failed at startup: GitHub rejected it before any job ran", [_startup_failed]),
	}
}

# METADATA
# title: An actions policy has not stopped every repository workflow
# custom:
#   code: ERR_CI_STATE_ACTIONS_RESTRICTED
deny contains denial if {
	_state.actions_enabled == true
	_restricted
	count(_repo_runs) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "an actions policy restricts what may run, and no repository workflow ran here",
	}
}

# METADATA
# title: The workflow file is registered with GitHub
# custom:
#   code: ERR_CI_STATE_WORKFLOW_UNREGISTERED
deny contains denial if {
	_state.workflows != null
	count(_registered) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "GitHub holds no registered repository workflow, so it has nothing to dispatch",
	}
}

# METADATA
# title: Every registered repository workflow is active
# custom:
#   code: ERR_CI_STATE_WORKFLOW_INACTIVE
deny contains denial if {
	count(_inactive) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%v not active: GitHub creates no run for a disabled workflow", [_inactive]),
	}
}

# METADATA
# title: A repository workflow was dispatched for the head
# custom:
#   code: ERR_CI_STATE_NO_RUN
deny contains denial if {
	_state.actions_enabled == true
	not _restricted
	_state.actions_status == "operational"
	_state.runs != null
	count(_registered) > 0
	count(_inactive) == 0
	count(_repo_runs) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "Actions is open and operational, yet no repository workflow ran on the head",
	}
}
