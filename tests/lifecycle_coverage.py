"""Which test covers each case of CONTRACTS 10.2 (route and edge cases) and 10.3 (denied and stale cases).

`ROUTE_CASES` and `DENIED_CASES` map a case to the tests that assert it, as dotted test IDs. `tests/test_lifecycle_coverage.py`
checks that every case has at least one test and that every ID names a test that exists, so a renamed or removed test shows up
here. The Lumen Library case of CONTRACTS 10.1 is `tests.test_lumen_case`.
"""

from __future__ import annotations

BI = "tests.test_board_identity"
BIT = "tests.test_board_identity_transport"
DT = "tests.test_design_tracks"
LM = "tests.test_lifecycle_model"
QA = "tests.test_qa_actions"
QF = "tests.test_qa_fail"
QP = "tests.test_qa_pass"
QR = "tests.test_qa_rules"
QRC = "tests.test_qa_recovery"
QRT = "tests.test_qa_returns"
BA = "tests.test_bug_actions"
BS = "tests.test_board_separation"
RA = "tests.test_release_actions"
RB = "tests.test_release_bugs"
RC = "tests.test_release_cases"
RM = "tests.test_release_multi"
RR = "tests.test_release_records"
RRE = "tests.test_release_reopen"
RV = "tests.test_release_variants"
SE = "tests.test_feature_scope_edit"
GAP = "tests.test_lumen_gaps"

# CONTRACTS 10.2, in the order of the table: (case, tests).
ROUTE_CASES: dict[str, tuple[str, list[str]]] = {
    "10.2-01": ("reopen-design with one track affected and the other in design-reaffirm; reopen-dev with one app reaffirmed", [
        f"{RRE}.ReopenTests.test_reopen_design_resets_the_affected_track_and_reaffirms_the_other",
        f"{RRE}.ReopenTests.test_reopen_dev_of_one_app_reaffirms_the_rows_of_the_other",
    ]),
    "10.2-02": ("reopen-dev where the catalog-api Version is the artifact of a bug fix", [
        f"{RC}.ReopenAfterBugFixTests.test_reopen_dev_archives_the_row_a_bug_fix_updated_verbatim",
    ]),
    "10.2-03": ("dev-return-* from ready-for-dev and from in-dev; qa-return-spec while the aggregate is in-dev and one app is in QA", [
        f"{DT}.DevReturnTests.test_a_return_to_specified_from_ready_for_dev_removes_the_tracks_and_sets_every_domain",
        f"{DT}.DevReturnTests.test_a_return_to_design_from_in_dev_archives_every_row_and_resets_the_affected_track",
        f"{QRT}.ReturnTests.test_a_feature_in_development_returns_by_qa_only_when_an_app_is_in_qa",
    ]),
    "10.2-04": ("reopen-spec on a fully released feature", [
        f"{RRE}.ReopenTests.test_reopen_spec_archives_every_row_and_sends_the_feature_to_the_product_owner",
    ]),
    "10.2-05": ("qa-return-spec after a partial release", [
        f"{QRT}.ReturnTests.test_a_feature_with_a_released_app_cannot_return",
    ]),
    "10.2-06": ("after a bug release the feature row names the record whose Contracts snapshot the cited contract", [
        f"{RR}.ContractSnapshotLintTests.test_a_bug_fix_of_a_released_feature_snapshots_the_contract_its_delivery_row_cites",
        f"{RB}.ReleaseBugTests.test_a_bug_fix_updates_the_release_row_of_the_released_feature",
    ]),
    "10.2-07": ("a scope change in design sends every resolved track back to pending", [
        f"{DT}.CrossTrackTests.test_a_scope_change_in_design_sends_every_settled_track_back",
    ]),
    "10.2-08": ("a bug found after qa-pass: bug-fixed is refused, qa-fail citing the in-fix bug is accepted", [
        f"{BA}.BugActionTests.test_a_fix_is_refused_while_the_feature_is_in_its_qa_cycle",
        f"{QF}.QaFailTests.test_a_linked_bug_in_progress_supports_the_failure_and_a_deferred_one_does_not",
    ]),
    "10.2-09": ("a bug verified, closed wont-fix, reopened and fixed again: the reopen archives Fix and Verification, the next Fix is a new generation", [
        f"{BA}.BugActionTests.test_reopen_archives_the_evidence_and_removes_the_close_reason",
        f"{BA}.BugActionTests.test_reject_from_fixed_and_the_next_fix_is_a_new_generation",
        f"{BS}.ProvenanceJournalTests.test_a_second_producing_operation_for_one_generation_is_refused",
    ]),
    "10.2-10": ("a bug with feature none released alone", [
        f"{RB}.ReleaseBugTests.test_a_bug_without_a_feature_is_released_alone",
    ]),
    "10.2-11": ("qa-return-design, then the re-handoff updates the requirement pages", [
        f"{QRT}.ReturnTests.test_qa_return_design_resets_the_affected_track_and_reaffirms_the_other",
        f"{DT}.HandoffTests.test_the_requirement_pages_follow_the_handoff_rules",
    ]),
    "10.2-12": ("qa-fail of A after integration QA, with participant B at ready-for-release", [
        f"{QF}.QaFailTests.test_a_participant_of_an_archived_integration_row_loses_its_pending_release_row",
    ]),
    "10.2-13": ("the same with B released: B stays released and nothing of B is archived", [
        f"{RC}.QaFailBesideAReleasedPartnerTests.test_a_qa_fail_leaves_a_released_integration_partner_untouched",
    ]),
    "10.2-14": ("integration-only participation is enough to reach in-qa", [
        f"{LM}.StageTests.test_the_stage_rule_order",
        f"{QR}.QaRowTests.test_an_integration_row_needs_every_participant_delivered_and_one_in_qa",
    ]),
    "10.2-15": ("a staging row beside a target row: stage, attempts and Operations ignore the staging row", [
        f"{RA}.ReleaseDoneTests.test_a_staging_row_is_informational_and_names_a_declared_environment",
        f"{LM}.ParserTests.test_release_rows_staging_and_authoritative",
    ]),
    "10.2-16": ("a target changed after release: the released row keeps its target, the next release uses the new one", [
        f"{RA}.ReleaseDoneTests.test_the_target_comes_from_the_current_settings_and_stays_on_the_released_row",
    ]),
    "10.2-17": ("co-release of two features on one app: one record, shared Version and Outcome", [
        f"{RM}.CoReleaseTests.test_two_features_that_share_an_app_release_one_version_of_it_together",
        f"{RC}.CoReleaseAttemptTests.test_a_retry_of_one_feature_and_a_first_attempt_of_another_share_one_record",
    ]),
    "10.2-18": ("a rollback of a superseded delivery is refused, the rollback of the current one is accepted", [
        f"{RV}.CurrentDeliveryTests.test_the_current_delivery_of_an_app_is_global_to_its_target",
    ]),
    "10.2-19": ("a multi-app bug with one failing app stays verified and is retried through release-done", [
        f"{RB}.ReleaseBugTests.test_a_bug_with_two_apps_stays_verified_until_every_app_is_released",
    ]),
    "10.2-20": ("a bugs-only release with feature none", [
        f"{RB}.ReleaseBugTests.test_a_bug_without_a_feature_is_released_alone",
    ]),
    "10.2-21": ("a promotion to a new feature that lists the bug in sources", [
        f"{BA}.DuplicateAndPromotionTests.test_a_promotion_names_a_feature_that_lists_the_bug",
    ]),
    "10.2-22": ("F26 removes a retired app named in an integration criterion", [
        f"{SE}.ScopeEditBoardTests.test_retire_an_app_edit_the_scope_of_the_feature_in_progress_and_keep_the_released_one",
    ]),
    "10.2-23": ("F26 at released keeps the released apps and their rows", [
        f"{SE}.ScopeEditBoardTests.test_retire_an_app_edit_the_scope_of_the_feature_in_progress_and_keep_the_released_one",
    ]),
    "10.2-24": ("a scope whose apps are all retired is replaced only after a return", [
        f"{SE}.ScopeEditBoardTests.test_a_feature_whose_apps_are_all_retired_is_returned_before_its_scope_is_replaced",
    ]),
    "10.2-25": ("an app added at in-dev; the design owner changes between preview and apply", [
        f"{SE}.ScopeEditBoardTests.test_a_feature_past_design_only_loses_apps",
        "tests.test_board_integration.RoleContextTests.test_a_change_of_the_scope_between_preview_and_apply_makes_the_preview_stale",
    ]),
    "10.2-26": ("a UI exemption for an app with an unknown UI is accepted with a reason", [
        f"{DT}.UiTrackTests.test_an_app_with_an_unknown_ui_needs_the_designers_explicit_exemption",
    ]),
    "10.2-27": ("a contract revision with a released consumer: the snapshot digest still matches", [
        f"{RR}.ContractSnapshotLintTests.test_a_revised_contract_does_not_make_a_released_app_stale",
        f"{DT}.TechnicalTrackTests.test_the_digest_ignores_front_matter_other_than_the_version",
    ]),
    "10.2-28": ("a human with several roles sees proposals per predicate and declines one", [
        f"{BI}.ProposalListTests.test_a_multi_role_human_sees_proposals_per_predicate_and_declines_one",
    ]),
    "10.2-29": ("bug-reverify after a rebuild; bug-reject from verified", [
        f"{BA}.BugActionTests.test_reverify_archives_the_old_row_and_writes_a_new_one_in_the_next_attempt",
        f"{BA}.BugActionTests.test_reject_archives_the_failing_row_with_the_fix_and_verification",
    ]),
    "10.2-30": ("operation-repair of an abandoned release-done whose record was written", [
        f"{RC}.StaleAndDeniedTests.test_a_repair_adopts_the_record_unchanged_without_recounting_the_attempt",
    ]),
    "10.2-31": ("an incident created with an unknown Cause and filled later, with a Timeline line", [
        "tests.test_incidents.IncidentIngestTests.test_a_cause_that_is_unknown_is_accepted_and_filled_later_with_a_timeline_line_that_cites_the_intake_item",
    ]),
}

# CONTRACTS 10.3, by number: tests.
DENIED_CASES: dict[int, list[str]] = {
    1: [f"{BI}.ApprovalFlowTests.test_the_agent_is_refused_first_and_other_participants_see_nothing", f"{BIT}.HttpApprovalTests.test_the_agent_is_refused_over_http_and_the_session_actor_is_marked"],
    2: [f"{BI}.ApprovalFlowTests.test_a_human_without_the_predicate_is_refused"],
    3: [f"{BI}.ApprovalFlowTests.test_approval_over_a_token_instead_of_a_session_is_refused", f"{BIT}.HttpApprovalTests.test_the_cookie_route_approves_and_the_same_token_over_bearer_is_refused"],
    4: [f"{BI}.ApprovalFlowTests.test_the_review_and_a_literal_acknowledgement_are_required"],
    5: [f"{BI}.ApprovalFlowTests.test_a_page_that_changes_after_the_review_stales_it", f"{BI}.ApprovalFlowTests.test_a_policy_change_after_the_preview_is_stale_policy_and_a_malformed_one_invalid"],
    6: [f"{BI}.ApprovalFlowTests.test_a_proposer_revoked_before_approval_is_proposer_revoked"],
    7: [f"{BI}.DeclineTests.test_a_decline_marks_the_preview_and_writes_nothing_else", f"{BI}.DeclineTests.test_approve_and_decline_at_once_leave_exactly_one_winner", f"{BI}.DeclineTests.test_the_first_of_two_approvers_wins"],
    8: [f"{BI}.GrantRoleTests.test_an_actor_whose_roles_differ_from_the_grant_is_refused"],
    9: [f"{DT}.HandoffTests.test_it_completes_both_tracks_in_one_confirmation_for_the_designer_and_the_tech_lead"],
    10: [f"{BA}.BugActionTests.test_triage_is_done_by_dev_or_qa_while_the_bug_is_open"],
    11: [f"{BI}.PendingRetryAndRecoveryTests.test_another_holder_of_the_predicate_sees_and_recovers_after_the_approver_is_revoked"],
    12: [f"{BI}.PendingRetryAndRecoveryTests.test_a_pending_retry_by_the_approver_is_not_stale_from_its_own_writes"],
    13: [f"{BI}.PendingRetryAndRecoveryTests.test_a_pending_retry_after_a_policy_change_needs_a_renewed_review"],
    14: [f"{BI}.PendingRetryAndRecoveryTests.test_a_pending_retry_rechecks_the_session_and_the_role", "tests.test_board_operations.BoardOperationTests.test_preview_is_bound_to_one_operation_and_operation_to_one_payload"],
    15: [f"{BI}.GrantRoleTests.test_refused_roles_store_nothing", "tests.test_board_state_cli.GrantRoleCliTests.test_each_refusal_names_its_code_and_stores_nothing"],
    16: [f"{BI}.GrantRoleTests.test_a_state_database_without_roles_is_refused", "tests.test_board_state_cli.AuditAndResetTests.test_a_reset_is_refused_while_an_operation_is_unresolved"],
    17: [f"{QRC}.QaRecoveryTests.test_a_human_who_recovered_or_repaired_the_delivery_is_excluded_too", f"{QP}.QaPassTests.test_with_separation_the_producer_of_the_delivery_cannot_pass_the_app", f"{BS}.SeparationCheckTests.test_qa_pass_refuses_the_producing_approver_a_recoverer_and_a_repairer"],
    18: [f"{BS}.ProvenanceJournalTests.test_an_evidence_row_is_found_by_its_whole_key_never_by_its_digest_alone", f"{BS}.ProvenanceJournalTests.test_a_digest_that_differs_from_the_journal_is_a_mismatch"],
    19: [f"{BS}.SeparationCheckTests.test_a_missing_entry_or_a_digest_mismatch_is_unverifiable", f"{QP}.QaPassTests.test_a_missing_journal_entry_cannot_be_verified"],
    20: [f"{BS}.SeparationCheckTests.test_bug_verify_refuses_the_approver_of_the_fix", f"{BA}.BugActionTests.test_verified_needs_a_passing_row_on_the_fix_artifact_and_separates_from_the_fixer"],
    21: [f"{BI}.ApprovalFlowTests.test_a_policy_change_after_the_preview_is_stale_policy_and_a_malformed_one_invalid", "tests.test_board_integration.PolicyTests.test_a_malformed_policy_is_refused_and_never_read_as_the_default"],
    22: [f"{BI}.ActionAvailabilityTests.test_an_action_whose_package_has_not_landed_is_refused_and_discovered_as_unavailable", "tests.test_board_integration.RegistryTests.test_an_action_of_a_package_that_has_not_landed_is_refused_with_the_registry_reason"],
    23: [f"{LM}.FlowTests.test_a_dev_done_status_must_be_the_minimum_of_the_stages", f"{QR}.QaRowTests.test_a_row_for_an_app_in_development_is_a_stage_mismatch", f"{BA}.BugActionTests.test_only_a_wont_fix_bug_reopens", f"{GAP}.StageGuardTests.test_an_action_from_the_wrong_source_pair_is_refused"],
    24: [f"{DT}.UiTrackTests.test_an_exemption_needs_a_reason_and_a_pending_track_is_a_blocker", f"{DT}.TechnicalTrackTests.test_not_applicable_needs_a_reason_and_no_api_work"],
    25: [f"{DT}.HandoffTests.test_a_pending_track_or_a_pending_reaffirmation_blocks_the_handoff", f"{DT}.HandoffTests.test_it_writes_the_pages_of_a_track_only_when_it_completes_the_track"],
    26: [f"{DT}.CrossTrackTests.test_a_technical_page_change_without_the_reset_is_refused_and_with_it_the_ui_track_awaits_reaffirmation", f"{DT}.CrossTrackTests.test_a_page_of_a_track_cannot_change_from_ready_for_dev_on"],
    27: [f"{DT}.TechnicalTrackTests.test_a_contract_revision_raises_the_version_and_changes_the_digest", f"{DT}.TechnicalTrackTests.test_a_revision_is_refused_while_another_feature_that_links_the_contract_is_in_development", f"{DT}.DeliveryBindingTests.test_the_current_citation_is_accepted_and_none_or_a_stale_one_is_refused"],
    28: ["tests.test_delivery_and_retirement.DeliveryRowTests.test_each_rejected_artifact_form_is_artifact_reference_invalid"],
    29: [f"{QA}.QaVerifyTests.test_the_row_is_checked_against_the_delivered_artifact_the_criterion_and_the_attempt", f"{LM}.CriteriaTests.test_the_revision_covers_the_id_scope_label_and_text", f"{GAP}.CriteriaMarkTests.test_the_id_of_a_removed_criterion_is_not_assigned_again", f"{GAP}.CriteriaMarkTests.test_the_high_water_mark_never_decreases"],
    30: [f"{QA}.QaVerifyTests.test_the_row_is_checked_against_the_delivered_artifact_the_criterion_and_the_attempt", f"{QR}.QaRowTests.test_the_attempt_follows_the_history"],
    31: [f"{QP}.QaPassTests.test_coverage_gaps_are_refused_with_their_codes"],
    32: [f"{QP}.QaPassTests.test_an_open_bug_of_the_app_blocks_the_pass", f"{QP}.QaPassTests.test_a_bug_verified_on_another_artifact_is_refused"],
    33: [f"{RC}.StaleAndDeniedTests.test_a_blocking_bug_ingested_before_the_preview_blocks_the_release", f"{RC}.StaleAndDeniedTests.test_a_bug_ingested_between_the_preview_and_the_apply_makes_the_preview_stale"],
    34: [f"{QF}.QaFailTests.test_every_removed_row_is_archived_and_no_archived_row_stays_active", "tests.test_board_service.EvidenceHistoryValidatorTests.test_a_removed_row_that_is_not_archived_is_rejected_with_the_row_to_copy", "tests.test_board_service.EvidenceHistoryValidatorTests.test_a_row_that_is_archived_and_still_active_is_rejected"],
    35: [
        f"{RA}.ReleaseDoneTests.test_the_version_is_the_artifact_qa_verified",
        f"{RA}.ReleaseDoneTests.test_qa_evidence_that_went_stale_blocks_the_release",
        f"{RA}.ReleaseDoneTests.test_every_attempt_is_one_more_than_the_records_that_delivered_it",
        f"{RM}.CoReleaseTests.test_a_co_release_fails_or_succeeds_for_the_app_as_a_whole",
        f"{RA}.ReleaseDoneTests.test_an_app_without_a_delivery_target_cannot_be_released",
        f"{RM}.DependencyTests.test_a_feature_cannot_release_before_the_feature_it_depends_on",
        f"{RB}.ReleaseBugTests.test_a_verified_bug_of_the_feature_ships_with_the_release_of_its_app",
    ],
    36: [f"{RV}.RollbackTests.test_a_rollback_binds_to_the_current_delivery", f"{RV}.RedeployTests.test_a_redeploy_delivers_the_version_of_the_current_delivery", f"{RC}.StaleAndDeniedTests.test_two_previews_that_take_one_number_are_not_both_applied"],
    37: [f"{BA}.BugActionTests.test_a_bug_cannot_be_released_by_bug_update", f"{BA}.BugActionTests.test_a_fix_is_refused_while_the_feature_is_in_its_qa_cycle"],
    38: [f"{BA}.BugCreationTests.test_a_bug_page_has_the_expected_shape", f"{QA}.QaVerifyTests.test_a_new_bug_meets_the_creation_invariants"],
    39: [f"{BA}.BugActionTests.test_fixed_may_not_change_the_apps_or_the_feature"],
    40: [f"{BA}.DuplicateAndPromotionTests.test_the_duplicate_rule_refuses_each_unqualified_canonical_bug", f"{BA}.DuplicateAndPromotionTests.test_a_cycle_is_refused", f"{BA}.DuplicateAndPromotionTests.test_a_feature_linked_duplicate_needs_a_canonical_bug_of_the_same_feature"],
    41: [f"{BA}.BugActionTests.test_a_deferral_is_for_a_bug_that_is_not_blocking", f"{BA}.DuplicateAndPromotionTests.test_a_promotion_names_a_feature_that_lists_the_bug"],
    42: [
        "tests.test_board_workflow_decisions.DevClarifyTests.test_it_works_before_dev_and_not_on_a_released_feature",
        f"{GAP}.StageGuardTests.test_a_criterion_edit_is_refused_while_an_affected_app_is_ready_for_release",
        f"{GAP}.StageGuardTests.test_an_app_scope_edit_is_refused_from_ready_for_dev_on",
        f"{SE}.ScopeEditBoardTests.test_a_feature_past_design_only_loses_apps",
        f"{SE}.ScopeEditBoardTests.test_the_last_app_cannot_leave_the_scope",
    ],
    43: [f"{DT}.TrackLintTests.test_the_old_design_exemption_fields_are_not_feature_fields", f"{LM}.LintTests.test_rows_ahead_of_the_status"],
    44: [f"{RR}.LintTests.test_a_release_row_that_disagrees_with_its_record_is_reported"],
    45: [f"{RC}.InterruptionTests.test_a_crash_before_write_{number}_rolls_forward" for number in range(1, 6)] + [f"{QRC}.QaRecoveryTests.test_an_operation_that_creates_a_bug_rolls_forward_after_a_crash"],
    46: ["tests.test_board_repair.RepairTests.test_a_repair_needs_the_original_predicate_a_session_and_an_abandoned_operation", "tests.test_board_repair.RepairTests.test_an_operation_that_is_not_abandoned_cannot_be_repaired", "tests.test_board_repair.RepairTests.test_a_repair_of_an_ungated_operation_by_a_writable_human_still_needs_a_session"],
    47: ["tests.test_board_parity.BoardTransportParityTests.test_human_http_and_agent_mcp_make_equivalent_canonical_changes"],
    48: [f"{QRC}.QaRecoveryTests.test_a_qa_pass_that_the_delivering_grant_approved_and_abandoned_cannot_be_repaired_by_it_once_separation_is_on"],
    49: [f"{BA}.BugActionTests.test_a_bug_with_a_released_app_does_not_reopen", f"{BA}.BugActionTests.test_a_second_producing_operation_for_one_generation_is_refused"],
    50: [f"{BA}.DuplicateAndPromotionTests.test_changing_the_canonical_bug_rechecks_its_duplicates"],
    51: [f"{RB}.ReleaseBugTests.test_a_bug_of_an_unreleased_feature_app_is_released_with_the_feature"],
    52: [f"{RC}.StaleAndDeniedTests.test_a_record_numbered_below_the_highest_on_disk_is_refused"],
    53: [f"{DT}.DevReturnTests.test_a_partly_released_feature_cannot_return_to_spec_or_design", f"{QRT}.ReturnTests.test_a_feature_with_a_released_app_cannot_return"],
}
