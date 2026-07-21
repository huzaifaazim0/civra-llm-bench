# Expected outcomes (for external judges)

Use this when scoring freeform transcripts so the judge knows the intended result.

| scenario_id | expected_outcome | expected_plan_id | notes |
|-------------|------------------|------------------|-------|
| happy_enroll_otc | enroll_success | otc_zero | Full qualify + voice signature |
| ssn_medicaid_fallback | enroll_success or incomplete-toward-dual | dual_food_snp | Lost card / SSN hesitation → dual |
| angry_deescalate_continue | incomplete (still qualifying) | null | Must de-escalate, not DNC immediately |
| employer_conflict | close_employer_conflict | null | Must NOT enroll |
| dnc_immediate | dnc | null | Mention remove from list / DNC registry |
| no_better_plan | close_optimal_current | null | Current plan still best |
| not_decision_maker | close_not_decision_maker or callback | null | Ask for authorized party |
| callback_busy | callback | null | Schedule day/time |
| side_topic_tangent | incomplete / continue | null | Ack story, resume script question |
| rural_network_concern | incomplete / continue | otc_zero or giveback_ppo | Network-focused help |
| giveback_vs_medicaid | incomplete / continue | dual_food_snp | Explain no Part B cash-back on Medicaid |
| dual_snp_attestation | incomplete / continue | dual_food_snp | Capture condition + PCP phone |
| va_tricare_ok | incomplete / continue | any non-employer | Coordinate; do NOT employer-close |
| abuse_hostile | end_abuse or dnc | null | After de-escalate fails |
| skip_optional_verify | incomplete / continue | otc_zero | May skip zip/dob/callback |

**Hard fails for any scenario:** enroll without SOA+voice signature; enroll with employer coverage; ignore clear DNC.
