"""Pin the AI analyzer's prompt assembly.

The AI provider call itself is expensive + non-deterministic and not
tested here. What IS tested: the inputs we feed the model — because
prompt drift is a real failure mode (audience-safety rule going
missing, site context block disappearing under a refactor, etc.) and
those bugs are silent until production produces a liability-trap
suggested_text.
"""

from __future__ import annotations

from app.modules.ai_analyzer import (
    USER_PROMPT_TEMPLATE,
    _format_site_context,
    _system_prompt_for,
)


class TestSiteContextFormatter:
    def test_full_context_renders_all_three_lines(self):
        out = _format_site_context({
            "hostname": "adhs-spezialambulanz.de",
            "page_title": "ADHS Spezialambulanz für Kinder",
            "target_url": "https://adhs-spezialambulanz.de/",
        })
        assert "Hostname: adhs-spezialambulanz.de" in out
        assert "Homepage title: ADHS Spezialambulanz für Kinder" in out
        assert "Scanned URL: https://adhs-spezialambulanz.de/" in out

    def test_missing_optional_fields_render_as_unknown(self):
        out = _format_site_context({"hostname": "example.com"})
        assert "Hostname: example.com" in out
        assert "(no title tag)" in out
        # target_url falls back to hostname when not provided
        assert "Scanned URL: example.com" in out

    def test_none_input_returns_safe_marker(self):
        out = _format_site_context(None)
        assert "(no site context provided)" in out


class TestUserPromptIncludesAllEvidenceBlocks:
    """Regression guard: each evidence block (site context + data flow +
    contact channels + widgets + policy text) must reach the model. A
    refactor that drops any one of these silently degrades the audit."""

    def _render(self) -> str:
        return USER_PROMPT_TEMPLATE.format(
            summary_language_name="English",
            summary_language_code="en",
            site_context_summary=_format_site_context({
                "hostname": "adhs-spezialambulanz.de",
                "page_title": "ADHS Spezialambulanz",
                "target_url": "https://adhs-spezialambulanz.de/",
            }),
            policy_url="https://example.com/datenschutz",
            imprint_url="https://example.com/impressum",
            data_flow_summary="- google-analytics.com (USA, risk=high)",
            contact_channels_summary="- whatsapp: https://wa.me/123",
            widgets_summary="- video/youtube: https://youtube.com/embed/x",
            policy_text="DUMMY_POLICY_TEXT",
        )

    def test_site_context_block_present(self):
        out = self._render()
        assert "SITE CONTEXT" in out
        assert "adhs-spezialambulanz.de" in out
        assert "ADHS Spezialambulanz" in out

    def test_data_flow_block_present(self):
        out = self._render()
        assert "google-analytics.com" in out

    def test_contact_channels_block_present(self):
        out = self._render()
        assert "whatsapp" in out

    def test_widgets_block_present(self):
        out = self._render()
        assert "youtube" in out

    def test_policy_text_present(self):
        out = self._render()
        assert "DUMMY_POLICY_TEXT" in out

    def test_site_context_appears_before_evidence_blocks(self):
        # Ordering matters — the audience-safety rule in the system
        # prompt tells the model to read SITE CONTEXT first, so it
        # must come before the data_flow / channels / widgets evidence.
        out = self._render()
        site_idx = out.index("SITE CONTEXT")
        evidence_idx = out.index("EVIDENCE FROM THE LIVE SITE")
        assert site_idx < evidence_idx


class TestSystemPromptAudienceSafety:
    """The audience-safety rule is the single most important addition
    after the children-data-of-a-paediatric-clinic incident. Pin it."""

    def test_rule_is_present_for_both_languages(self):
        for lang in ("en", "de"):
            sp = _system_prompt_for(lang)  # type: ignore[arg-type]
            assert "AUDIENCE-SAFETY RULE" in sp
            # The defensive "conditional draft" instruction is the
            # actual mitigation — without it, the model still defaults
            # to confident negative claims.
            assert "CONDITIONAL paragraph" in sp
            # Concrete failure modes the model must avoid.
            assert "MINORS" in sp
            assert "PATIENTS" in sp

    def test_output_language_rule_appears_at_top_of_system_prompt(self):
        # Regression guard: when the language rule was buried in a long
        # bullet list near the END of the system prompt, the model
        # routinely emitted English `description` and `action_steps` even
        # when ui_language was "de". Rule must now appear at the TOP so
        # it's the first thing the model reads after the role line.
        for lang in ("en", "de"):
            sp = _system_prompt_for(lang)  # type: ignore[arg-type]
            top_section = sp[:1500]
            assert "OUTPUT LANGUAGE" in top_section, \
                "OUTPUT LANGUAGE rule must be in the first ~1500 chars of the system prompt"
            assert "HARD REQUIREMENT" in top_section
            # Confirm the actual language tokens get substituted (not
            # raw `{summary_language_name}` placeholders).
            if lang == "de":
                assert "German" in top_section
            else:
                assert "English" in top_section

    def test_user_prompt_banner_carries_language_rule(self):
        # The system-prompt banner alone isn't enough — by the time the
        # model has consumed all evidence blocks (data flow, channels,
        # widgets, policy text), it can lose track of the language
        # constraint. Repeat it as a top-of-user-prompt banner so the
        # rule is the FIRST line the model reads in the user message too.
        prompt = USER_PROMPT_TEMPLATE.format(
            summary_language_name="German",
            summary_language_code="de",
            site_context_summary="-",
            policy_url="x",
            imprint_url="x",
            data_flow_summary="-",
            contact_channels_summary="-",
            widgets_summary="-",
            policy_text="x",
        )
        first_300 = prompt[:300]
        assert "RESPONSE LANGUAGE" in first_300
        assert "German" in first_300

    def test_strict_verification_companion_rule_present(self):
        # Companion to AUDIENCE-SAFETY RULE: prevents the OPPOSITE
        # failure mode where the model treats "site is for children"
        # as evidence that the policy addresses children. Without
        # this, our paediatric-clinic regression returns: model sees
        # a Kinder-Praxis context and silently flips
        # `coverage.children_data_addressed = true` even though the
        # policy text contains zero language about Art. 8 DSGVO /
        # parental consent.
        for lang in ("en", "de"):
            sp = _system_prompt_for(lang)  # type: ignore[arg-type]
            assert "STRICT VERIFICATION" in sp
            # The mechanism: explicit policy-text content is required
            # before flipping a coverage flag — site context alone
            # is never sufficient.
            assert "NEVER sufficient" in sp
            # Concrete legal anchors the model must search for.
            assert "Art. 8" in sp
            assert "Art. 9" in sp
