"""namespace every table with ``bountyflow_`` so the database can be shared with another project

Postgres keeps index and constraint names when a table is renamed, but ``NAMING_CONVENTION`` in
``app/db/base.py`` derives them from the table, so each one is renamed alongside its table. A name that
would pass 63 characters carries the suffix SQLAlchemy appends when it truncates one of its own
(``<first 55 characters>_<last 4 of the name's md5>``), so the result is what the models compile to.

``alembic_version`` is not renamed here: Alembic resolves its version table before it runs any migration,
so ``migrations/env.py`` adopts it on the connection first.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREFIX = "bountyflow_"

TABLES: tuple[str, ...] = (
    "account_deletion_requests",
    "asset_operations",
    "audit_logs",
    "blockchain_transactions",
    "bounties",
    "bounty_applications",
    "bounty_assignments",
    "bounty_bookmarks",
    "bounty_escrows",
    "bounty_milestones",
    "bounty_qa_posts",
    "bounty_qa_votes",
    "bounty_skills",
    "bounty_submissions",
    "bounty_tags",
    "bounty_view_daily",
    "completion_attestations",
    "daily_metrics",
    "data_exports",
    "dispute_evidence",
    "dispute_votes",
    "disputes",
    "email_deliveries",
    "email_verification_tokens",
    "feedback",
    "github_accounts",
    "legal_acceptances",
    "legal_document_versions",
    "notification_preferences",
    "notifications",
    "outbox_events",
    "passkey_wallets",
    "password_reset_tokens",
    "payment_records",
    "processed_events",
    "reward_assets",
    "saved_search_matches",
    "saved_searches",
    "screening_entries",
    "skill_edges",
    "skill_nodes",
    "sponsored_transactions",
    "submission_pull_requests",
    "submission_revisions",
    "user_reports",
    "user_sessions",
    "user_skills",
    "users",
    "verifiable_credentials",
    "wallets",
)

# (table, current name, prefixed name) for every primary key, foreign key, unique and check constraint.
CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    # account_deletion_requests
    ("account_deletion_requests", "ck_account_deletion_requests_deletion_status", "ck_bountyflow_account_deletion_requests_deletion_status"),
    ("account_deletion_requests", "fk_account_deletion_requests_user_id_users", "fk_bountyflow_account_deletion_requests_user_id_bountyf_06bb"),
    ("account_deletion_requests", "pk_account_deletion_requests", "pk_bountyflow_account_deletion_requests"),
    # asset_operations
    ("asset_operations", "ck_asset_operations_asset_operation_kind", "ck_bountyflow_asset_operations_asset_operation_kind"),
    ("asset_operations", "ck_asset_operations_asset_operation_status", "ck_bountyflow_asset_operations_asset_operation_status"),
    ("asset_operations", "fk_asset_operations_asset_id_reward_assets", "fk_bountyflow_asset_operations_asset_id_bountyflow_rewa_f8b2"),
    ("asset_operations", "fk_asset_operations_sponsorship_id_sponsored_transactions", "fk_bountyflow_asset_operations_sponsorship_id_bountyflo_530b"),
    ("asset_operations", "fk_asset_operations_user_id_users", "fk_bountyflow_asset_operations_user_id_bountyflow_users"),
    ("asset_operations", "pk_asset_operations", "pk_bountyflow_asset_operations"),
    ("asset_operations", "uq_asset_operations_network_hash", "uq_bountyflow_asset_operations_network_hash"),
    # audit_logs
    ("audit_logs", "fk_audit_logs_actor_id_users", "fk_bountyflow_audit_logs_actor_id_bountyflow_users"),
    ("audit_logs", "fk_audit_logs_bounty_id_bounties", "fk_bountyflow_audit_logs_bounty_id_bountyflow_bounties"),
    ("audit_logs", "pk_audit_logs", "pk_bountyflow_audit_logs"),
    # blockchain_transactions
    ("blockchain_transactions", "ck_blockchain_transactions_tx_status", "ck_bountyflow_blockchain_transactions_tx_status"),
    ("blockchain_transactions", "ck_blockchain_transactions_tx_type", "ck_bountyflow_blockchain_transactions_tx_type"),
    ("blockchain_transactions", "fk_blockchain_transactions_assignment_id_bounty_assignments", "fk_bountyflow_blockchain_transactions_assignment_id_bou_03ad"),
    ("blockchain_transactions", "fk_blockchain_transactions_bounty_id_bounties", "fk_bountyflow_blockchain_transactions_bounty_id_bountyf_baf2"),
    ("blockchain_transactions", "fk_blockchain_transactions_dispute_id_disputes", "fk_bountyflow_blockchain_transactions_dispute_id_bounty_a033"),
    ("blockchain_transactions", "fk_blockchain_transactions_submission_id_bounty_submissions", "fk_bountyflow_blockchain_transactions_submission_id_bou_9305"),
    ("blockchain_transactions", "fk_blockchain_transactions_user_id_users", "fk_bountyflow_blockchain_transactions_user_id_bountyflow_users"),
    ("blockchain_transactions", "pk_blockchain_transactions", "pk_bountyflow_blockchain_transactions"),
    ("blockchain_transactions", "uq_blockchain_transactions_network_hash", "uq_bountyflow_blockchain_transactions_network_hash"),
    # bounties
    ("bounties", "ck_bounties_bounty_category", "ck_bountyflow_bounties_bounty_category"),
    ("bounties", "ck_bounties_bounty_difficulty", "ck_bountyflow_bounties_bounty_difficulty"),
    ("bounties", "ck_bounties_bounty_status", "ck_bountyflow_bounties_bounty_status"),
    ("bounties", "ck_bounties_bounty_visibility", "ck_bountyflow_bounties_bounty_visibility"),
    ("bounties", "ck_bounties_deadline_order", "ck_bountyflow_bounties_deadline_order"),
    ("bounties", "ck_bounties_positions_range", "ck_bountyflow_bounties_positions_range"),
    ("bounties", "ck_bounties_review_window_range", "ck_bountyflow_bounties_review_window_range"),
    ("bounties", "ck_bounties_reward_positive", "ck_bountyflow_bounties_reward_positive"),
    ("bounties", "fk_bounties_requester_id_users", "fk_bountyflow_bounties_requester_id_bountyflow_users"),
    ("bounties", "pk_bounties", "pk_bountyflow_bounties"),
    ("bounties", "uq_bounties_slug", "uq_bountyflow_bounties_slug"),
    # bounty_applications
    ("bounty_applications", "ck_bounty_applications_application_status", "ck_bountyflow_bounty_applications_application_status"),
    ("bounty_applications", "fk_bounty_applications_bounty_id_bounties", "fk_bountyflow_bounty_applications_bounty_id_bountyflow_bounties"),
    ("bounty_applications", "fk_bounty_applications_contributor_id_users", "fk_bountyflow_bounty_applications_contributor_id_bounty_1e6e"),
    ("bounty_applications", "fk_bounty_applications_reviewed_by_id_users", "fk_bountyflow_bounty_applications_reviewed_by_id_bounty_427f"),
    ("bounty_applications", "pk_bounty_applications", "pk_bountyflow_bounty_applications"),
    # bounty_assignments
    ("bounty_assignments", "ck_bounty_assignments_assignment_status", "ck_bountyflow_bounty_assignments_assignment_status"),
    ("bounty_assignments", "fk_bounty_assignments_application_id_bounty_applications", "fk_bountyflow_bounty_assignments_application_id_bountyf_a2f9"),
    ("bounty_assignments", "fk_bounty_assignments_bounty_id_bounties", "fk_bountyflow_bounty_assignments_bounty_id_bountyflow_bounties"),
    ("bounty_assignments", "fk_bounty_assignments_contributor_id_users", "fk_bountyflow_bounty_assignments_contributor_id_bountyf_97ef"),
    ("bounty_assignments", "pk_bounty_assignments", "pk_bountyflow_bounty_assignments"),
    ("bounty_assignments", "uq_bounty_assignments_application_id", "uq_bountyflow_bounty_assignments_application_id"),
    # bounty_bookmarks
    ("bounty_bookmarks", "fk_bounty_bookmarks_bounty_id_bounties", "fk_bountyflow_bounty_bookmarks_bounty_id_bountyflow_bounties"),
    ("bounty_bookmarks", "fk_bounty_bookmarks_user_id_users", "fk_bountyflow_bounty_bookmarks_user_id_bountyflow_users"),
    ("bounty_bookmarks", "pk_bounty_bookmarks", "pk_bountyflow_bounty_bookmarks"),
    ("bounty_bookmarks", "uq_bounty_bookmarks_user_id_bounty_id", "uq_bountyflow_bounty_bookmarks_user_id_bounty_id"),
    # bounty_escrows
    ("bounty_escrows", "ck_bounty_escrows_amounts", "ck_bountyflow_bounty_escrows_amounts"),
    ("bounty_escrows", "ck_bounty_escrows_conservation", "ck_bountyflow_bounty_escrows_conservation"),
    ("bounty_escrows", "ck_bounty_escrows_escrow_state", "ck_bountyflow_bounty_escrows_escrow_state"),
    ("bounty_escrows", "fk_bounty_escrows_bounty_id_bounties", "fk_bountyflow_bounty_escrows_bounty_id_bountyflow_bounties"),
    ("bounty_escrows", "pk_bounty_escrows", "pk_bountyflow_bounty_escrows"),
    ("bounty_escrows", "uq_bounty_escrows_bounty_id", "uq_bountyflow_bounty_escrows_bounty_id"),
    ("bounty_escrows", "uq_bounty_escrows_onchain_bounty_id", "uq_bountyflow_bounty_escrows_onchain_bounty_id"),
    # bounty_milestones
    ("bounty_milestones", "ck_bounty_milestones_amount_positive", "ck_bountyflow_bounty_milestones_amount_positive"),
    ("bounty_milestones", "ck_bounty_milestones_milestone_status", "ck_bountyflow_bounty_milestones_milestone_status"),
    ("bounty_milestones", "ck_bounty_milestones_position_range", "ck_bountyflow_bounty_milestones_position_range"),
    ("bounty_milestones", "fk_bounty_milestones_bounty_id_bounties", "fk_bountyflow_bounty_milestones_bounty_id_bountyflow_bounties"),
    ("bounty_milestones", "fk_bounty_milestones_payout_tx_blockchain_transactions", "fk_bountyflow_bounty_milestones_payout_tx_blockchain_tx"),
    ("bounty_milestones", "pk_bounty_milestones", "pk_bountyflow_bounty_milestones"),
    ("bounty_milestones", "uq_bounty_milestones_bounty_position", "uq_bountyflow_bounty_milestones_bounty_position"),
    # bounty_qa_posts
    ("bounty_qa_posts", "ck_bounty_qa_posts_questions_not_accepted", "ck_bountyflow_bounty_qa_posts_questions_not_accepted"),
    ("bounty_qa_posts", "ck_bounty_qa_posts_replies_not_pinned", "ck_bountyflow_bounty_qa_posts_replies_not_pinned"),
    ("bounty_qa_posts", "ck_bounty_qa_posts_upvotes_non_negative", "ck_bountyflow_bounty_qa_posts_upvotes_non_negative"),
    ("bounty_qa_posts", "fk_bounty_qa_posts_author_id_users", "fk_bountyflow_bounty_qa_posts_author_id_bountyflow_users"),
    ("bounty_qa_posts", "fk_bounty_qa_posts_bounty_id_bounties", "fk_bountyflow_bounty_qa_posts_bounty_id_bountyflow_bounties"),
    ("bounty_qa_posts", "fk_bounty_qa_posts_hidden_by_id_users", "fk_bountyflow_bounty_qa_posts_hidden_by_id_bountyflow_users"),
    ("bounty_qa_posts", "fk_bounty_qa_posts_parent_id_bounty_qa_posts", "fk_bountyflow_bounty_qa_posts_parent_id_bountyflow_boun_bbc9"),
    ("bounty_qa_posts", "pk_bounty_qa_posts", "pk_bountyflow_bounty_qa_posts"),
    # bounty_qa_votes
    ("bounty_qa_votes", "fk_bounty_qa_votes_post_id_bounty_qa_posts", "fk_bountyflow_bounty_qa_votes_post_id_bountyflow_bounty_093d"),
    ("bounty_qa_votes", "fk_bounty_qa_votes_user_id_users", "fk_bountyflow_bounty_qa_votes_user_id_bountyflow_users"),
    ("bounty_qa_votes", "pk_bounty_qa_votes", "pk_bountyflow_bounty_qa_votes"),
    # bounty_skills
    ("bounty_skills", "fk_bounty_skills_bounty_id_bounties", "fk_bountyflow_bounty_skills_bounty_id_bountyflow_bounties"),
    ("bounty_skills", "pk_bounty_skills", "pk_bountyflow_bounty_skills"),
    ("bounty_skills", "uq_bounty_skills_bounty_id_skill_name", "uq_bountyflow_bounty_skills_bounty_id_skill_name"),
    # bounty_submissions
    ("bounty_submissions", "ck_bounty_submissions_onchain_review_state", "ck_bountyflow_bounty_submissions_onchain_review_state"),
    ("bounty_submissions", "ck_bounty_submissions_submission_status", "ck_bountyflow_bounty_submissions_submission_status"),
    ("bounty_submissions", "fk_bounty_submissions_assignment_id_bounty_assignments", "fk_bountyflow_bounty_submissions_assignment_id_bountyfl_e80b"),
    ("bounty_submissions", "fk_bounty_submissions_bounty_id_bounties", "fk_bountyflow_bounty_submissions_bounty_id_bountyflow_bounties"),
    ("bounty_submissions", "fk_bounty_submissions_contributor_id_users", "fk_bountyflow_bounty_submissions_contributor_id_bountyf_a777"),
    ("bounty_submissions", "fk_bounty_submissions_milestone_id_bounty_milestones", "fk_bountyflow_bounty_submissions_milestone_id_bountyflo_57ef"),
    ("bounty_submissions", "fk_bounty_submissions_reviewer_id_users", "fk_bountyflow_bounty_submissions_reviewer_id_bountyflow_users"),
    ("bounty_submissions", "pk_bounty_submissions", "pk_bountyflow_bounty_submissions"),
    # bounty_tags
    ("bounty_tags", "fk_bounty_tags_bounty_id_bounties", "fk_bountyflow_bounty_tags_bounty_id_bountyflow_bounties"),
    ("bounty_tags", "pk_bounty_tags", "pk_bountyflow_bounty_tags"),
    ("bounty_tags", "uq_bounty_tags_bounty_id_tag", "uq_bountyflow_bounty_tags_bounty_id_tag"),
    # bounty_view_daily
    ("bounty_view_daily", "fk_bounty_view_daily_bounty_id_bounties", "fk_bountyflow_bounty_view_daily_bounty_id_bountyflow_bounties"),
    ("bounty_view_daily", "pk_bounty_view_daily", "pk_bountyflow_bounty_view_daily"),
    # completion_attestations
    ("completion_attestations", "ck_completion_attestations_amount_positive", "ck_bountyflow_completion_attestations_amount_positive"),
    ("completion_attestations", "ck_completion_attestations_attestation_chain_check", "ck_bountyflow_completion_attestations_attestation_chain_check"),
    ("completion_attestations", "ck_completion_attestations_attestation_status", "ck_bountyflow_completion_attestations_attestation_status"),
    ("completion_attestations", "ck_completion_attestations_payments_counted", "ck_bountyflow_completion_attestations_payments_counted"),
    ("completion_attestations", "fk_completion_attestations_assignment_id_bounty_assignments", "fk_bountyflow_completion_attestations_assignment_id_bou_fa96"),
    ("completion_attestations", "fk_completion_attestations_bounty_id_bounties", "fk_bountyflow_completion_attestations_bounty_id_bountyf_1704"),
    ("completion_attestations", "fk_completion_attestations_contributor_id_users", "fk_bountyflow_completion_attestations_contributor_id_bo_d19e"),
    ("completion_attestations", "fk_completion_attestations_payout_transaction_id_blockc_92dc", "fk_bountyflow_completion_attestations_payout_transactio_e3dd"),
    ("completion_attestations", "fk_completion_attestations_revoked_by_id_users", "fk_bountyflow_completion_attestations_revoked_by_id_bou_fc9a"),
    ("completion_attestations", "pk_completion_attestations", "pk_bountyflow_completion_attestations"),
    ("completion_attestations", "uq_completion_attestations_bounty_contributor", "uq_bountyflow_completion_attestations_bounty_contributor"),
    ("completion_attestations", "uq_completion_attestations_onchain", "uq_bountyflow_completion_attestations_onchain"),
    # daily_metrics
    ("daily_metrics", "pk_daily_metrics", "pk_bountyflow_daily_metrics"),
    # data_exports
    ("data_exports", "ck_data_exports_export_status", "ck_bountyflow_data_exports_export_status"),
    ("data_exports", "fk_data_exports_user_id_users", "fk_bountyflow_data_exports_user_id_bountyflow_users"),
    ("data_exports", "pk_data_exports", "pk_bountyflow_data_exports"),
    # dispute_evidence
    ("dispute_evidence", "fk_dispute_evidence_dispute_id_disputes", "fk_bountyflow_dispute_evidence_dispute_id_bountyflow_disputes"),
    ("dispute_evidence", "fk_dispute_evidence_submitted_by_id_users", "fk_bountyflow_dispute_evidence_submitted_by_id_bountyflow_users"),
    ("dispute_evidence", "pk_dispute_evidence", "pk_bountyflow_dispute_evidence"),
    # dispute_votes
    ("dispute_votes", "fk_dispute_votes_bounty_id_bounties", "fk_bountyflow_dispute_votes_bounty_id_bountyflow_bounties"),
    ("dispute_votes", "fk_dispute_votes_dispute_id_disputes", "fk_bountyflow_dispute_votes_dispute_id_bountyflow_disputes"),
    ("dispute_votes", "fk_dispute_votes_transaction_id_blockchain_transactions", "fk_bountyflow_dispute_votes_transaction_id_bountyflow_b_87c4"),
    ("dispute_votes", "fk_dispute_votes_voter_id_users", "fk_bountyflow_dispute_votes_voter_id_bountyflow_users"),
    ("dispute_votes", "pk_dispute_votes", "pk_bountyflow_dispute_votes"),
    ("dispute_votes", "uq_dispute_votes_arbiter_round", "uq_bountyflow_dispute_votes_arbiter_round"),
    # disputes
    ("disputes", "ck_disputes_dispute_resolution", "ck_bountyflow_disputes_dispute_resolution"),
    ("disputes", "ck_disputes_dispute_status", "ck_bountyflow_disputes_dispute_status"),
    ("disputes", "fk_disputes_assigned_moderator_id_users", "fk_bountyflow_disputes_assigned_moderator_id_bountyflow_users"),
    ("disputes", "fk_disputes_bounty_id_bounties", "fk_bountyflow_disputes_bounty_id_bountyflow_bounties"),
    ("disputes", "fk_disputes_contributor_id_users", "fk_bountyflow_disputes_contributor_id_bountyflow_users"),
    ("disputes", "fk_disputes_raised_by_id_users", "fk_bountyflow_disputes_raised_by_id_bountyflow_users"),
    ("disputes", "fk_disputes_resolved_by_id_users", "fk_bountyflow_disputes_resolved_by_id_bountyflow_users"),
    ("disputes", "pk_disputes", "pk_bountyflow_disputes"),
    # email_deliveries
    ("email_deliveries", "ck_email_deliveries_email_status", "ck_bountyflow_email_deliveries_email_status"),
    ("email_deliveries", "fk_email_deliveries_user_id_users", "fk_bountyflow_email_deliveries_user_id_bountyflow_users"),
    ("email_deliveries", "pk_email_deliveries", "pk_bountyflow_email_deliveries"),
    ("email_deliveries", "uq_email_deliveries_idempotency", "uq_bountyflow_email_deliveries_idempotency"),
    # email_verification_tokens
    ("email_verification_tokens", "fk_email_verification_tokens_user_id_users", "fk_bountyflow_email_verification_tokens_user_id_bountyf_d4bc"),
    ("email_verification_tokens", "pk_email_verification_tokens", "pk_bountyflow_email_verification_tokens"),
    ("email_verification_tokens", "uq_email_verification_tokens_token_hash", "uq_bountyflow_email_verification_tokens_token_hash"),
    # feedback
    ("feedback", "ck_feedback_feedback_kind", "ck_bountyflow_feedback_feedback_kind"),
    ("feedback", "ck_feedback_feedback_status", "ck_bountyflow_feedback_feedback_status"),
    ("feedback", "fk_feedback_handled_by_id_users", "fk_bountyflow_feedback_handled_by_id_bountyflow_users"),
    ("feedback", "fk_feedback_user_id_users", "fk_bountyflow_feedback_user_id_bountyflow_users"),
    ("feedback", "pk_feedback", "pk_bountyflow_feedback"),
    # github_accounts
    ("github_accounts", "ck_github_accounts_github_link_method", "ck_bountyflow_github_accounts_github_link_method"),
    ("github_accounts", "fk_github_accounts_user_id_users", "fk_bountyflow_github_accounts_user_id_bountyflow_users"),
    ("github_accounts", "pk_github_accounts", "pk_bountyflow_github_accounts"),
    ("github_accounts", "uq_github_accounts_github_id", "uq_bountyflow_github_accounts_github_id"),
    # legal_acceptances
    ("legal_acceptances", "ck_legal_acceptances_legal_document", "ck_bountyflow_legal_acceptances_legal_document"),
    ("legal_acceptances", "fk_legal_acceptances_user_id_users", "fk_bountyflow_legal_acceptances_user_id_bountyflow_users"),
    ("legal_acceptances", "fk_legal_acceptances_version_id_legal_document_versions", "fk_bountyflow_legal_acceptances_version_id_bountyflow_l_9ac9"),
    ("legal_acceptances", "pk_legal_acceptances", "pk_bountyflow_legal_acceptances"),
    ("legal_acceptances", "uq_legal_acceptances_user_version", "uq_bountyflow_legal_acceptances_user_version"),
    # legal_document_versions
    ("legal_document_versions", "ck_legal_document_versions_legal_document", "ck_bountyflow_legal_document_versions_legal_document"),
    ("legal_document_versions", "fk_legal_document_versions_published_by_id_users", "fk_bountyflow_legal_document_versions_published_by_id_b_8d8d"),
    ("legal_document_versions", "fk_legal_document_versions_withdrawn_by_id_users", "fk_bountyflow_legal_document_versions_withdrawn_by_id_b_5682"),
    ("legal_document_versions", "pk_legal_document_versions", "pk_bountyflow_legal_document_versions"),
    ("legal_document_versions", "uq_legal_document_versions_document_version", "uq_bountyflow_legal_document_versions_document_version"),
    # notification_preferences
    ("notification_preferences", "fk_notification_preferences_user_id_users", "fk_bountyflow_notification_preferences_user_id_bountyflow_users"),
    ("notification_preferences", "pk_notification_preferences", "pk_bountyflow_notification_preferences"),
    # notifications
    ("notifications", "ck_notifications_notification_type", "ck_bountyflow_notifications_notification_type"),
    ("notifications", "fk_notifications_user_id_users", "fk_bountyflow_notifications_user_id_bountyflow_users"),
    ("notifications", "pk_notifications", "pk_bountyflow_notifications"),
    ("notifications", "uq_notifications_user_event", "uq_bountyflow_notifications_user_event"),
    # outbox_events
    ("outbox_events", "pk_outbox_events", "pk_bountyflow_outbox_events"),
    # passkey_wallets
    ("passkey_wallets", "ck_passkey_wallets_passkey_wallet_status", "ck_bountyflow_passkey_wallets_passkey_wallet_status"),
    ("passkey_wallets", "fk_passkey_wallets_user_id_users", "fk_bountyflow_passkey_wallets_user_id_bountyflow_users"),
    ("passkey_wallets", "pk_passkey_wallets", "pk_bountyflow_passkey_wallets"),
    ("passkey_wallets", "uq_passkey_wallets_network_contract", "uq_bountyflow_passkey_wallets_network_contract"),
    ("passkey_wallets", "uq_passkey_wallets_network_key", "uq_bountyflow_passkey_wallets_network_key"),
    # password_reset_tokens
    ("password_reset_tokens", "fk_password_reset_tokens_user_id_users", "fk_bountyflow_password_reset_tokens_user_id_bountyflow_users"),
    ("password_reset_tokens", "pk_password_reset_tokens", "pk_bountyflow_password_reset_tokens"),
    ("password_reset_tokens", "uq_password_reset_tokens_token_hash", "uq_bountyflow_password_reset_tokens_token_hash"),
    # payment_records
    ("payment_records", "ck_payment_records_payment_status", "ck_bountyflow_payment_records_payment_status"),
    ("payment_records", "fk_payment_records_blockchain_transaction_id_blockchain_eb1e", "fk_bountyflow_payment_records_blockchain_transaction_id_1857"),
    ("payment_records", "fk_payment_records_bounty_id_bounties", "fk_bountyflow_payment_records_bounty_id_bountyflow_bounties"),
    ("payment_records", "fk_payment_records_contributor_id_users", "fk_bountyflow_payment_records_contributor_id_bountyflow_users"),
    ("payment_records", "fk_payment_records_milestone_id_bounty_milestones", "fk_bountyflow_payment_records_milestone_id_bountyflow_b_6773"),
    ("payment_records", "fk_payment_records_submission_id_bounty_submissions", "fk_bountyflow_payment_records_submission_id_bountyflow__23ad"),
    ("payment_records", "pk_payment_records", "pk_bountyflow_payment_records"),
    ("payment_records", "uq_payment_records_submission", "uq_bountyflow_payment_records_submission"),
    # processed_events
    ("processed_events", "pk_processed_events", "pk_bountyflow_processed_events"),
    # reward_assets
    ("reward_assets", "ck_reward_assets_reward_asset_contract_status", "ck_bountyflow_reward_assets_reward_asset_contract_status"),
    ("reward_assets", "ck_reward_assets_reward_asset_kind", "ck_bountyflow_reward_assets_reward_asset_kind"),
    ("reward_assets", "fk_reward_assets_created_by_id_users", "fk_bountyflow_reward_assets_created_by_id_bountyflow_users"),
    ("reward_assets", "pk_reward_assets", "pk_bountyflow_reward_assets"),
    ("reward_assets", "uq_reward_assets_network_contract", "uq_bountyflow_reward_assets_network_contract"),
    ("reward_assets", "uq_reward_assets_network_identifier", "uq_bountyflow_reward_assets_network_identifier"),
    # saved_search_matches
    ("saved_search_matches", "ck_saved_search_matches_saved_search_match_delivery", "ck_bountyflow_saved_search_matches_saved_search_match_delivery"),
    ("saved_search_matches", "fk_saved_search_matches_bounty_id_bounties", "fk_bountyflow_saved_search_matches_bounty_id_bountyflow_c476"),
    ("saved_search_matches", "fk_saved_search_matches_saved_search_id_saved_searches", "fk_bountyflow_saved_search_matches_saved_search_id_boun_4be4"),
    ("saved_search_matches", "pk_saved_search_matches", "pk_bountyflow_saved_search_matches"),
    # saved_searches
    ("saved_searches", "ck_saved_searches_saved_search_alert_frequency", "ck_bountyflow_saved_searches_saved_search_alert_frequency"),
    ("saved_searches", "fk_saved_searches_user_id_users", "fk_bountyflow_saved_searches_user_id_bountyflow_users"),
    ("saved_searches", "pk_saved_searches", "pk_bountyflow_saved_searches"),
    # screening_entries
    ("screening_entries", "ck_screening_entries_screening_source", "ck_bountyflow_screening_entries_screening_source"),
    ("screening_entries", "fk_screening_entries_added_by_id_users", "fk_bountyflow_screening_entries_added_by_id_bountyflow_users"),
    ("screening_entries", "fk_screening_entries_removed_by_id_users", "fk_bountyflow_screening_entries_removed_by_id_bountyflow_users"),
    ("screening_entries", "pk_screening_entries", "pk_bountyflow_screening_entries"),
    # skill_edges
    ("skill_edges", "pk_skill_edges", "pk_bountyflow_skill_edges"),
    # skill_nodes
    ("skill_nodes", "pk_skill_nodes", "pk_bountyflow_skill_nodes"),
    # sponsored_transactions
    ("sponsored_transactions", "ck_sponsored_transactions_sponsorship_kind", "ck_bountyflow_sponsored_transactions_sponsorship_kind"),
    ("sponsored_transactions", "ck_sponsored_transactions_sponsorship_status", "ck_bountyflow_sponsored_transactions_sponsorship_status"),
    ("sponsored_transactions", "fk_sponsored_transactions_blockchain_transaction_id_blo_8424", "fk_bountyflow_sponsored_transactions_blockchain_transac_1da8"),
    ("sponsored_transactions", "fk_sponsored_transactions_passkey_wallet_id_passkey_wallets", "fk_bountyflow_sponsored_transactions_passkey_wallet_id__9591"),
    ("sponsored_transactions", "fk_sponsored_transactions_user_id_users", "fk_bountyflow_sponsored_transactions_user_id_bountyflow_users"),
    ("sponsored_transactions", "pk_sponsored_transactions", "pk_bountyflow_sponsored_transactions"),
    ("sponsored_transactions", "uq_sponsored_transactions_network_envelope", "uq_bountyflow_sponsored_transactions_network_envelope"),
    # submission_pull_requests
    ("submission_pull_requests", "ck_submission_pull_requests_pr_checks_status", "ck_bountyflow_submission_pull_requests_pr_checks_status"),
    ("submission_pull_requests", "ck_submission_pull_requests_pr_state", "ck_bountyflow_submission_pull_requests_pr_state"),
    ("submission_pull_requests", "ck_submission_pull_requests_pr_verification", "ck_bountyflow_submission_pull_requests_pr_verification"),
    ("submission_pull_requests", "fk_submission_pull_requests_submission_id_bounty_submissions", "fk_bountyflow_submission_pull_requests_submission_id_bo_fc5b"),
    ("submission_pull_requests", "pk_submission_pull_requests", "pk_bountyflow_submission_pull_requests"),
    ("submission_pull_requests", "uq_submission_pull_requests_pr", "uq_bountyflow_submission_pull_requests_pr"),
    # submission_revisions
    ("submission_revisions", "fk_submission_revisions_submission_id_bounty_submissions", "fk_bountyflow_submission_revisions_submission_id_bounty_0679"),
    ("submission_revisions", "pk_submission_revisions", "pk_bountyflow_submission_revisions"),
    ("submission_revisions", "uq_submission_revisions_submission_id_version", "uq_bountyflow_submission_revisions_submission_id_version"),
    # user_reports
    ("user_reports", "ck_user_reports_report_status", "ck_bountyflow_user_reports_report_status"),
    ("user_reports", "ck_user_reports_report_target", "ck_bountyflow_user_reports_report_target"),
    ("user_reports", "fk_user_reports_reporter_id_users", "fk_bountyflow_user_reports_reporter_id_bountyflow_users"),
    ("user_reports", "fk_user_reports_resolved_by_id_users", "fk_bountyflow_user_reports_resolved_by_id_bountyflow_users"),
    ("user_reports", "pk_user_reports", "pk_bountyflow_user_reports"),
    # user_sessions
    ("user_sessions", "fk_user_sessions_user_id_users", "fk_bountyflow_user_sessions_user_id_bountyflow_users"),
    ("user_sessions", "pk_user_sessions", "pk_bountyflow_user_sessions"),
    ("user_sessions", "uq_user_sessions_refresh_token_hash", "uq_bountyflow_user_sessions_refresh_token_hash"),
    # user_skills
    ("user_skills", "fk_user_skills_user_id_users", "fk_bountyflow_user_skills_user_id_bountyflow_users"),
    ("user_skills", "pk_user_skills", "pk_bountyflow_user_skills"),
    ("user_skills", "uq_user_skills_user_id_skill_name", "uq_bountyflow_user_skills_user_id_skill_name"),
    # users
    ("users", "ck_users_user_role", "ck_bountyflow_users_user_role"),
    ("users", "pk_users", "pk_bountyflow_users"),
    ("users", "uq_users_normalized_email", "uq_bountyflow_users_normalized_email"),
    ("users", "uq_users_username", "uq_bountyflow_users_username"),
    # verifiable_credentials
    ("verifiable_credentials", "ck_verifiable_credentials_credential_kind", "ck_bountyflow_verifiable_credentials_credential_kind"),
    ("verifiable_credentials", "fk_verifiable_credentials_attestation_id_completion_att_7c34", "fk_bountyflow_verifiable_credentials_attestation_id_bou_3773"),
    ("verifiable_credentials", "fk_verifiable_credentials_user_id_users", "fk_bountyflow_verifiable_credentials_user_id_bountyflow_users"),
    ("verifiable_credentials", "pk_verifiable_credentials", "pk_bountyflow_verifiable_credentials"),
    ("verifiable_credentials", "uq_verifiable_credentials_status_index", "uq_bountyflow_verifiable_credentials_status_index"),
    # wallets
    ("wallets", "ck_wallets_wallet_verification_status", "ck_bountyflow_wallets_wallet_verification_status"),
    ("wallets", "fk_wallets_user_id_users", "fk_bountyflow_wallets_user_id_bountyflow_users"),
    ("wallets", "pk_wallets", "pk_bountyflow_wallets"),
)

# The same, for the indexes that no constraint owns (renaming a constraint renames its index with it).
INDEXES: tuple[tuple[str, str], ...] = (
    # account_deletion_requests
    ("ix_account_deletion_requests_status_due", "ix_bountyflow_account_deletion_requests_status_due"),
    ("ix_account_deletion_requests_user_id", "ix_bountyflow_account_deletion_requests_user_id"),
    ("uq_account_deletion_requests_one_scheduled", "uq_bountyflow_account_deletion_requests_one_scheduled"),
    # asset_operations
    ("ix_asset_operations_asset_id", "ix_bountyflow_asset_operations_asset_id"),
    ("ix_asset_operations_status", "ix_bountyflow_asset_operations_status"),
    ("ix_asset_operations_user_created", "ix_bountyflow_asset_operations_user_created"),
    # audit_logs
    ("ix_audit_logs_action", "ix_bountyflow_audit_logs_action"),
    ("ix_audit_logs_actor_id", "ix_bountyflow_audit_logs_actor_id"),
    ("ix_audit_logs_bounty_created", "ix_bountyflow_audit_logs_bounty_created"),
    ("ix_audit_logs_entity", "ix_bountyflow_audit_logs_entity"),
    ("ix_audit_logs_screening", "ix_bountyflow_audit_logs_screening"),
    # blockchain_transactions
    ("ix_blockchain_transactions_assignment_id", "ix_bountyflow_blockchain_transactions_assignment_id"),
    ("ix_blockchain_transactions_bounty_id", "ix_bountyflow_blockchain_transactions_bounty_id"),
    ("ix_blockchain_transactions_submission_id", "ix_bountyflow_blockchain_transactions_submission_id"),
    ("ix_blockchain_transactions_user_id", "ix_bountyflow_blockchain_transactions_user_id"),
    ("ix_blockchain_tx_bounty_created", "ix_bountyflow_blockchain_tx_bounty_created"),
    ("ix_blockchain_tx_status", "ix_bountyflow_blockchain_tx_status"),
    # bounties
    ("ix_bounties_category", "ix_bountyflow_bounties_category"),
    ("ix_bounties_difficulty", "ix_bountyflow_bounties_difficulty"),
    ("ix_bounties_listed_at", "ix_bountyflow_bounties_listed_at"),
    ("ix_bounties_requester_id", "ix_bountyflow_bounties_requester_id"),
    ("ix_bounties_requester_status", "ix_bountyflow_bounties_requester_status"),
    ("ix_bounties_reward_asset_identifier", "ix_bountyflow_bounties_reward_asset_identifier"),
    ("ix_bounties_search_vector", "ix_bountyflow_bounties_search_vector"),
    ("ix_bounties_status", "ix_bountyflow_bounties_status"),
    ("ix_bounties_status_published", "ix_bountyflow_bounties_status_published"),
    # bounty_applications
    ("ix_applications_bounty_status", "ix_bountyflow_applications_bounty_status"),
    ("ix_bounty_applications_bounty_id", "ix_bountyflow_bounty_applications_bounty_id"),
    ("ix_bounty_applications_contributor_id", "ix_bountyflow_bounty_applications_contributor_id"),
    ("uq_applications_one_active", "uq_bountyflow_applications_one_active"),
    # bounty_assignments
    ("ix_bounty_assignments_bounty_id", "ix_bountyflow_bounty_assignments_bounty_id"),
    ("ix_bounty_assignments_contributor_id", "ix_bountyflow_bounty_assignments_contributor_id"),
    ("uq_assignments_one_live", "uq_bountyflow_assignments_one_live"),
    # bounty_bookmarks
    ("ix_bounty_bookmarks_bounty_id", "ix_bountyflow_bounty_bookmarks_bounty_id"),
    ("ix_bounty_bookmarks_user_id", "ix_bountyflow_bounty_bookmarks_user_id"),
    # bounty_milestones
    ("ix_bounty_milestones_bounty_id", "ix_bountyflow_bounty_milestones_bounty_id"),
    ("ix_bounty_milestones_bounty_position", "ix_bountyflow_bounty_milestones_bounty_position"),
    # bounty_qa_posts
    ("ix_bounty_qa_posts_author_created", "ix_bountyflow_bounty_qa_posts_author_created"),
    ("ix_bounty_qa_posts_author_id", "ix_bountyflow_bounty_qa_posts_author_id"),
    ("ix_bounty_qa_posts_bounty_id", "ix_bountyflow_bounty_qa_posts_bounty_id"),
    ("ix_bounty_qa_posts_bounty_thread", "ix_bountyflow_bounty_qa_posts_bounty_thread"),
    ("ix_bounty_qa_posts_parent_id", "ix_bountyflow_bounty_qa_posts_parent_id"),
    ("ix_bounty_qa_posts_visible_questions", "ix_bountyflow_bounty_qa_posts_visible_questions"),
    ("uq_bounty_qa_posts_accepted_reply", "uq_bountyflow_bounty_qa_posts_accepted_reply"),
    # bounty_qa_votes
    ("ix_bounty_qa_votes_user_id", "ix_bountyflow_bounty_qa_votes_user_id"),
    # bounty_skills
    ("ix_bounty_skills_bounty_id", "ix_bountyflow_bounty_skills_bounty_id"),
    ("ix_bounty_skills_normalized", "ix_bountyflow_bounty_skills_normalized"),
    ("ix_bounty_skills_skill_name", "ix_bountyflow_bounty_skills_skill_name"),
    # bounty_submissions
    ("ix_bounty_submissions_assignment_id", "ix_bountyflow_bounty_submissions_assignment_id"),
    ("ix_bounty_submissions_bounty_id", "ix_bountyflow_bounty_submissions_bounty_id"),
    ("ix_bounty_submissions_claimable", "ix_bountyflow_bounty_submissions_claimable"),
    ("ix_bounty_submissions_contributor_id", "ix_bountyflow_bounty_submissions_contributor_id"),
    ("ix_bounty_submissions_milestone_id", "ix_bountyflow_bounty_submissions_milestone_id"),
    # bounty_tags
    ("ix_bounty_tags_bounty_id", "ix_bountyflow_bounty_tags_bounty_id"),
    ("ix_bounty_tags_normalized", "ix_bountyflow_bounty_tags_normalized"),
    ("ix_bounty_tags_tag", "ix_bountyflow_bounty_tags_tag"),
    # completion_attestations
    ("ix_completion_attestations_bounty_id", "ix_bountyflow_completion_attestations_bounty_id"),
    ("ix_completion_attestations_checked", "ix_bountyflow_completion_attestations_checked"),
    ("ix_completion_attestations_contributor_status", "ix_bountyflow_completion_attestations_contributor_status"),
    ("ix_completion_attestations_due", "ix_bountyflow_completion_attestations_due"),
    ("ix_completion_attestations_payout_transaction_id", "ix_bountyflow_completion_attestations_payout_transaction_id"),
    # data_exports
    ("ix_data_exports_status", "ix_bountyflow_data_exports_status"),
    ("ix_data_exports_user_created", "ix_bountyflow_data_exports_user_created"),
    # dispute_evidence
    ("ix_dispute_evidence_dispute_id", "ix_bountyflow_dispute_evidence_dispute_id"),
    # dispute_votes
    ("ix_dispute_votes_dispute_id", "ix_bountyflow_dispute_votes_dispute_id"),
    # disputes
    ("ix_disputes_bounty_id", "ix_bountyflow_disputes_bounty_id"),
    ("ix_disputes_contributor_id", "ix_bountyflow_disputes_contributor_id"),
    ("ix_disputes_raised_by_id", "ix_bountyflow_disputes_raised_by_id"),
    ("uq_disputes_one_open_per_bounty", "uq_bountyflow_disputes_one_open_per_bounty"),
    # email_deliveries
    ("ix_email_deliveries_user_id", "ix_bountyflow_email_deliveries_user_id"),
    # email_verification_tokens
    ("ix_email_verification_tokens_user_id", "ix_bountyflow_email_verification_tokens_user_id"),
    # feedback
    ("ix_feedback_created", "ix_bountyflow_feedback_created"),
    ("ix_feedback_kind_created", "ix_bountyflow_feedback_kind_created"),
    ("ix_feedback_status_created", "ix_bountyflow_feedback_status_created"),
    ("ix_feedback_user_id", "ix_bountyflow_feedback_user_id"),
    # legal_acceptances
    ("ix_legal_acceptances_user_id", "ix_bountyflow_legal_acceptances_user_id"),
    # legal_document_versions
    ("ix_legal_document_versions_document_effective", "ix_bountyflow_legal_document_versions_document_effective"),
    # notifications
    ("ix_notifications_user_created", "ix_bountyflow_notifications_user_created"),
    ("ix_notifications_user_id", "ix_bountyflow_notifications_user_id"),
    # outbox_events
    ("ix_outbox_unpublished", "ix_bountyflow_outbox_unpublished"),
    # passkey_wallets
    ("ix_passkey_wallets_user_id", "ix_bountyflow_passkey_wallets_user_id"),
    # password_reset_tokens
    ("ix_password_reset_tokens_user_id", "ix_bountyflow_password_reset_tokens_user_id"),
    # payment_records
    ("ix_payment_records_bounty_id", "ix_bountyflow_payment_records_bounty_id"),
    ("ix_payment_records_contributor_id", "ix_bountyflow_payment_records_contributor_id"),
    ("uq_payment_records_bounty_contributor", "uq_bountyflow_payment_records_bounty_contributor"),
    ("uq_payment_records_milestone", "uq_bountyflow_payment_records_milestone"),
    # reward_assets
    ("ix_reward_assets_network_enabled", "ix_bountyflow_reward_assets_network_enabled"),
    # saved_search_matches
    ("ix_saved_search_matches_bounty_id", "ix_bountyflow_saved_search_matches_bounty_id"),
    ("ix_saved_search_matches_pending", "ix_bountyflow_saved_search_matches_pending"),
    ("ix_saved_search_matches_search_matched", "ix_bountyflow_saved_search_matches_search_matched"),
    # saved_searches
    ("ix_saved_searches_digest_due", "ix_bountyflow_saved_searches_digest_due"),
    ("ix_saved_searches_user_id", "ix_bountyflow_saved_searches_user_id"),
    # screening_entries
    ("ix_screening_entries_address", "ix_bountyflow_screening_entries_address"),
    ("uq_screening_entries_active", "uq_bountyflow_screening_entries_active"),
    # sponsored_transactions
    ("ix_sponsored_transactions_blockchain_transaction_id", "ix_bountyflow_sponsored_transactions_blockchain_transaction_id"),
    ("ix_sponsored_transactions_created", "ix_bountyflow_sponsored_transactions_created"),
    ("ix_sponsored_transactions_passkey_wallet_id", "ix_bountyflow_sponsored_transactions_passkey_wallet_id"),
    ("ix_sponsored_transactions_user_created", "ix_bountyflow_sponsored_transactions_user_created"),
    # submission_pull_requests
    ("ix_submission_pull_requests_head_sha", "ix_bountyflow_submission_pull_requests_head_sha"),
    ("ix_submission_pull_requests_next_check_at", "ix_bountyflow_submission_pull_requests_next_check_at"),
    ("ix_submission_pull_requests_repo_number", "ix_bountyflow_submission_pull_requests_repo_number"),
    ("ix_submission_pull_requests_submission_id", "ix_bountyflow_submission_pull_requests_submission_id"),
    # submission_revisions
    ("ix_submission_revisions_submission_id", "ix_bountyflow_submission_revisions_submission_id"),
    # user_reports
    ("ix_user_reports_reporter_id", "ix_bountyflow_user_reports_reporter_id"),
    ("ix_user_reports_status", "ix_bountyflow_user_reports_status"),
    ("ix_user_reports_target", "ix_bountyflow_user_reports_target"),
    # user_sessions
    ("ix_user_sessions_previous_token_hash", "ix_bountyflow_user_sessions_previous_token_hash"),
    ("ix_user_sessions_user_id", "ix_bountyflow_user_sessions_user_id"),
    # user_skills
    ("ix_user_skills_normalized", "ix_bountyflow_user_skills_normalized"),
    ("ix_user_skills_skill_name", "ix_bountyflow_user_skills_skill_name"),
    ("ix_user_skills_user_id", "ix_bountyflow_user_skills_user_id"),
    # verifiable_credentials
    ("ix_verifiable_credentials_revoked", "ix_bountyflow_verifiable_credentials_revoked"),
    ("ix_verifiable_credentials_user_kind", "ix_bountyflow_verifiable_credentials_user_kind"),
    ("ix_verifiable_credentials_user_standing", "ix_bountyflow_verifiable_credentials_user_standing"),
    ("uq_verifiable_credentials_active_completion", "uq_bountyflow_verifiable_credentials_active_completion"),
    # wallets
    ("ix_wallets_public_address", "ix_bountyflow_wallets_public_address"),
    ("ix_wallets_user_id", "ix_bountyflow_wallets_user_id"),
    ("uq_wallets_active_address_network", "uq_bountyflow_wallets_active_address_network"),
)


def _rename_constraints(pairs: Sequence[tuple[str, str, str]]) -> None:
    for table, old, new in pairs:
        op.execute(f"ALTER TABLE {PREFIX}{table} RENAME CONSTRAINT {old} TO {new}")


def _rename_indexes(pairs: Sequence[tuple[str, str]]) -> None:
    for old, new in pairs:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def upgrade() -> None:
    for table in TABLES:
        op.rename_table(table, f"{PREFIX}{table}")
    _rename_constraints(CONSTRAINTS)
    _rename_indexes(INDEXES)


def downgrade() -> None:
    _rename_constraints([(table, new, old) for table, old, new in reversed(CONSTRAINTS)])
    _rename_indexes([(new, old) for old, new in reversed(INDEXES)])
    for table in reversed(TABLES):
        op.rename_table(f"{PREFIX}{table}", table)
