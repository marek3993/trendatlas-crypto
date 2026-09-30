"""Public migration errors are a closed vocabulary, never protected log text."""
import json

REASONS = {
    'production target needs the current closed day': 'CURRENT_CLOSED_DAY_REQUIRED',
    'readback is stale or unsafe': 'READBACK_UNSAFE',
    'account preflight is not ready': 'ACCOUNT_PREFLIGHT_BLOCKED',
    'execution lease is present': 'EXECUTION_LEASE_PRESENT',
    'deployment readiness gates are incomplete': 'READINESS_INCOMPLETE',
    'readiness receipt does not bind capabilities': 'CAPABILITIES_CHANGED',
    'runtime manifest mismatch': 'RUNTIME_MANIFEST_MISMATCH',
    'installed systemd unit drift': 'SYSTEMD_DRIFT',
    'production service is running': 'PRODUCTION_BUSY',
    'VPS must still be disabled and no-submit': 'VPS_POSTURE_UNSAFE',
    'account/signer/journal identity mismatch': 'HOST_HANDOFF_MISMATCH',
    'single execution host not established': 'SINGLE_HOST_NOT_ESTABLISHED',
}
CODES = set(REASONS.values()) | {
    'REMOTE_FAILURE', 'UNCLASSIFIED_FAILURE', 'RECEIPT_UNBOUND', 'RECEIPT_EXPIRED',
    'RECEIPT_DAY_CHANGED', 'RECEIPT_TARGET_CHANGED', 'RECEIPT_ACCOUNT_CHANGED',
    'RECEIPT_JOURNAL_CHANGED', 'RECEIPT_PLANNER_CHANGED', 'REPLAY_UNBOUND', 'RECEIPT_INPUTS_CHANGED',
    'PUBLICATION_PENDING', 'SUBMISSION_UNRESOLVED', 'SERVICE_COMMAND_FAILED', 'CAPABILITIES_UNREADABLE',
    'SSH_CONNECTION_TIMEOUT', 'SSH_CONNECTION_CLOSED', 'SSH_AUTH_FAILED',
}
PHASES = {'PREFLIGHT_PI', 'PREFLIGHT_VPS', 'PREFLIGHT_COMPARE', 'WAIT_PI',
          'FENCING_PI', 'PI_FENCED', 'CHECKPOINTED', 'ACTIVATING', 'VPS_ACTIVE',
          'RUN_REQUESTED', 'RECONCILE_REQUIRED', 'SUCCESS', 'NEW', 'PREPARED',
          'PI_RESTORED_BEFORE_ACTIVATION'}


class MigrationError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'UNCLASSIFIED_FAILURE'
        super().__init__(self.code)


def reason_code(error):
    return error.code if isinstance(error, MigrationError) else REASONS.get(str(error), 'UNCLASSIFIED_FAILURE')


def remote_error(stdout):
    try:
        value = json.loads(stdout)
        code = value.get('reason_code') if isinstance(value, dict) else None
    except (ValueError, TypeError):
        code = None
    return MigrationError(code if isinstance(code, str) and code in CODES else 'REMOTE_FAILURE')


def failure_report(error, state, phase=None):
    saved = state.get('phase', 'NEW')
    phase = phase if phase in PHASES else saved if saved in PHASES else 'NEW'
    possible = (saved in {'ACTIVATING', 'VPS_ACTIVE', 'RUN_REQUESTED', 'RECONCILE_REQUIRED', 'SUCCESS'}) if saved in PHASES else None
    fenced = True if saved in {'PI_FENCED', 'CHECKPOINTED'} else None
    if saved in {'NEW', 'PREPARED', 'PI_RESTORED_BEFORE_ACTIVATION'}:
        fenced = False
    return {'reason_code': reason_code(error), 'phase': phase,
            'pi_fenced': fenced, 'live_activation_possible': possible}
