"""The label schema. Single source of truth for the codebook given to coders
(human, agent or API model) and for validating what they return.

One label per passage, produced in one pass. Every label carries the taxonomy
version, so results from different versions never get mixed silently.

Every value is defined as a one-line definition plus a short checklist of
criteria that must all hold (modelled on how PRISON, Wu et al., ICLR 2026,
defines its traits). The criteria are what make borderline passages decidable.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

TAXONOMY_VERSION = "0.5"

# Each value: (definition, criteria). A value applies only if all its criteria hold.
Definition = tuple[str, tuple[str, ...]]

# v0.4: the frame of the AI statement is fixed before any role or trait is judged. Criteria
# marked "frame-dependent" below are read in that frame.
FRAMES: dict[str, Definition] = {
    "risk_factor": (
        "The AI statement sits in a risk disclosure: a risk-factor section or a sentence stating possible harm.",
        (
            "the passage is in a risk-factor section or under a heading naming risks (Item 1A, \"Risk Factors\"), "
            "or the sentence states a possible harm, loss, cost, failure or shortfall for the company",
            "the AI statement is part of that risk disclosure, not a business description or an oversight "
            "remit that happens to be near it",
        ),
    ),
    "governance": (
        "The AI statement describes an oversight structure, policy, control, review, committee remit or "
        "assigned responsibility.",
        (
            "the sentence names an oversight structure, policy, control, review, committee, framework or "
            "assigned responsibility of the company (board, audit committee, management review, cybersecurity "
            "programme)",
            "AI appears within what that structure covers, as its subject or as an item in its remit",
            "the function of the sentence is to describe the oversight, not the company's operations and not "
            "a harm",
        ),
    ),
    "business": (
        "The AI statement describes the company's own operations, products, services, projects or plans.",
        (
            "the sentence describes what the company does, makes, sells, builds or plans (operations, products, "
            "services, projects, strategy)",
            "the company (or \"we\") is the actor of that description",
            "the function of the sentence is to describe the business, not a harm (`risk_factor`), an oversight "
            "remit (`governance`) or a market (`market`)",
        ),
    ),
    "market": (
        "The AI statement describes demand, prices, supply, investment or market conditions for what the "
        "company sells or buys.",
        (
            "the sentence describes demand, prices, supply, investment or market conditions",
            "those conditions concern what the company sells or buys (its customers' or suppliers' side), and AI "
            "or AI-linked infrastructure is their subject or cause",
            "the function of the sentence is to describe the market, not a harm (`risk_factor`) and not the "
            "company's own operations (`business`)",
        ),
    ),
}

AI_REFERENCE: dict[str, Definition] = {
    "explicit": (
        "The passage names AI or a clearly AI-specific technique.",
        (
            "a term for AI or an AI-specific technique appears (artificial intelligence, machine learning, "
            "generative AI, LLM, neural network, ...)",
            "the term is used in its technology sense, not as part of an unrelated name, abbreviation or "
            "keyword false positive",
        ),
    ),
    "implicit": (
        "AI is not named, but AI-linked infrastructure or demand is treated as a factor for the company's "
        "business or market.",
        (
            "no AI term appears (otherwise `explicit`)",
            "the passage names AI-linked infrastructure or demand: data centres, hyperscalers, compute, the "
            "power they consume, or companies named as AI-infrastructure buyers",
            "that infrastructure or demand is presented as a factor for the company's business, market or "
            "risks, even in passing, not as the company's own facility in an unrelated sense",
        ),
    ),
    "none": (
        "Not about AI.",
        (
            "no AI term is used in its technology sense",
            "any matched term appears in an unrelated sense (the company's own data centre in a "
            "disaster-recovery sentence, an abbreviation, a keyword false positive)",
            "nothing in the passage links infrastructure or demand to AI",
        ),
    ),
}

ROLES: dict[str, Definition] = {
    "market_driver": (
        "AI drives demand, prices or market conditions for what the company sells or buys.",
        (
            "the passage describes demand, prices, supply, investment or market conditions on the company's "
            "selling or buying side (frame-dependent: in frame `market` this is the primary role; in any "
            "other frame an explicit demand, price or supply statement must appear in the passage)",
            "AI (or, for `implicit`, AI-linked infrastructure) is named as a cause of that demand or condition",
            "the content is demand-side or market-side: a passage that only says the company uses, sells or "
            "governs AI does not qualify",
        ),
    ),
    "adoption": (
        "The company itself uses, pilots or plans to use AI.",
        (
            "the passage names the company (or \"we\") as the user, not vendors, customers or attackers",
            "a use, trial or stated intention is asserted, not merely a possibility inside a risk statement "
            "(frame-dependent: in frame `governance` the assertion must come from a clause outside the "
            "governance remit; \"AI usage\" named inside a review or control remit does not count)",
            "the use concerns AI as defined under `ai_reference` `explicit`",
        ),
    ),
    "offering": (
        "The company develops or sells AI products or services.",
        (
            "the passage names the company (or \"we\") as the developer, provider or seller",
            "what is developed or sold is itself AI, or a product or service whose AI capability is presented "
            "as part of what the customer gets",
            "the development or sale is asserted or presupposed, not merely a possibility inside a risk "
            "statement",
        ),
    ),
    "risk": (
        "AI is a source or amplifier of a risk to the company.",
        (
            "the passage states a possible harm, loss, cost, failure or shortfall for the company, including "
            "an AI-driven opportunity that may not materialise",
            "AI is named as the cause, amplifier or object of that harm, not merely nearby in an unrelated "
            "sentence",
            "the harm is stated as possible or expected; a harm that has happened is `incident` (both when "
            "the passage states both)",
        ),
    ),
    "governance": (
        "Oversight, policies, controls or responsibilities that the company sets up for AI.",
        (
            "the passage names an oversight structure, policy, control, review, committee, framework or "
            "assigned responsibility of the company",
            "AI is within its remit, either as its subject or as an item inside a broader remit "
            "(cybersecurity programme, enterprise risk review, board oversight)",
            "the structure is the company's own, not a regulator's rule or a vendor's control "
            "(frame-dependent: the role applies in any frame if its criteria hold; in frame `governance` it "
            "is the primary role)",
        ),
    ),
    "incident": (
        "A harm or loss involving AI that has actually happened.",
        (
            "the passage reports an event as having occurred (a breach, error, outage, loss, claim, fine), "
            "in the past or present tense",
            "AI was involved in causing or carrying out the event",
            "the event concerns the company, its customers, suppliers or operations, not an event elsewhere "
            "cited as an example of a risk",
        ),
    ),
    "general": (
        "AI is mentioned without any of the roles above.",
        (
            "the passage is about AI (`explicit` or `implicit`)",
            "no other role meets all its criteria (macro commentary, definitions, glossary entries, "
            "industry background)",
        ),
    ),
}

RISK_TYPES: dict[str, Definition] = {
    "market_demand": (
        "AI-driven demand or investment may slow, shift or fail to materialise.",
        (
            "the risk concerns demand, prices, investment or market conditions for what the company sells or "
            "buys",
            "that demand or investment is attributed to AI (or AI-linked infrastructure)",
            "the stated harm is that the company sells less, earns less or does not capture the AI-driven "
            "opportunity, including when the company's own failure to capture it is the cause",
        ),
    ),
    "strategic_competitive": (
        "Falling behind competitors on AI, or disruption of the business model by AI.",
        (
            "the harm is a loss of competitive position, market share or business-model viability",
            "the mechanism is competitors', substitutes' or the market's use of AI, or the company's lag in "
            "adopting or offering AI",
            "the passage does not merely say that an AI-driven market opportunity may be missed (that is "
            "`market_demand`)",
        ),
    ),
    "operational_reliability": (
        "AI systems that are wrong, biased, unsafe or misused internally.",
        (
            "the harm arises from the behaviour of an AI system: wrong, biased, unsafe, unreliable or "
            "non-compliant outputs, or misuse by the company's own staff",
            "the AI system is one the company uses, builds or relies on in its operations or products",
            "no attacker is the cause of the failure (deliberate manipulation or poisoning by an attacker is "
            "`cybersecurity`)",
        ),
    ),
    "cybersecurity": (
        "AI-enabled attacks or fraud; AI systems as an attack surface.",
        (
            "an adversary or attacker is named or implied (attacks, fraud, phishing, deepfake impersonation, "
            "manipulation or poisoning of training data, prompt injection)",
            "AI is the attacker's tool, or the target or attack surface",
            "the harm is to the company's systems, data, funds or customers",
        ),
    ),
    "third_party": (
        "AI used by vendors or service providers; dependence on AI suppliers.",
        (
            "the AI belongs to or is operated by a vendor, service provider, partner or supplier",
            "the harm reaches the company through its reliance on that party (their failure, misuse, outage, "
            "terms or availability)",
            "the party is in a supply or service relationship with the company, not a customer (customer-side "
            "risk reaching the company through demand is `market_demand`)",
        ),
    ),
    "regulatory_legal": (
        "AI-specific regulation, liability, privacy or intellectual-property exposure.",
        (
            "the harm is legal or regulatory: compliance costs, restrictions, enforcement, liability, "
            "litigation, privacy or intellectual-property claims",
            "the law, regulation or claim is tied to AI (AI-specific rules, or general rules as applied to AI)",
            "the passage links the regulation or claim to the company's own activities, costs or obligations, "
            "even in general terms",
        ),
    ),
    "workforce": (
        "Displacement, skills gaps, labour relations.",
        (
            "the harm concerns the company's employees or hiring: displacement, skills gaps, retention, "
            "labour relations, training",
            "AI is the cause (AI replacing tasks, demand for AI skills, employee response to AI)",
        ),
    ),
    "reputational_ethical": (
        "Loss of trust, fairness and ethics concerns.",
        (
            "the passage contains trust, fairness, discrimination, ethics, transparency or social-acceptance "
            "content",
            "that content is linked to the company's use, offering or handling of AI",
            "the harm is stated as loss of trust or ethical standing, not only as a consequence word "
            "(\"poses risks to our reputation\" alone does not qualify)",
        ),
    ),
    "information_integrity": (
        "Misinformation, deepfakes, content authenticity.",
        (
            "the harm concerns false, misleading, manipulated or unverifiable information or content",
            "AI generates or spreads that content, or undermines its verification",
            "the harm reaches the company, its markets, customers or reputation (impersonation used to "
            "defraud the company is also `cybersecurity`)",
        ),
    ),
    "environmental": (
        "Energy, carbon or resource burden of AI as a downside for the company.",
        (
            "the harm concerns energy, water, carbon, emissions or other resource use",
            "AI (or AI-linked infrastructure such as data centres) is the cause of that burden",
            "the burden is presented as a downside for the company (costs, targets, constraints, scrutiny), "
            "not as a demand opportunity",
        ),
    ),
    "other": (
        "A stated AI risk that fits none of the above.",
        (
            "the passage states a risk attributed to AI (the `risk` role applies)",
            "no other risk type meets all its criteria",
            "`note` explains the risk",
        ),
    ),
}

ADOPTION_STAGES: dict[str, Definition] = {
    "planned": (
        "Intention or possibility only.",
        (
            "the company's own use is stated as an intention, plan, expectation or possibility (\"may expand "
            "our use of AI\", \"intend to\", \"are evaluating\")",
            "no current use or trial of the same AI is stated",
        ),
    ),
    "piloting": (
        "Trial, proof of concept, limited test.",
        (
            "the company's own use is stated as a pilot, trial, proof of concept, test or experiment",
            "no production or business-as-usual use of the same AI is stated",
        ),
    ),
    "deployed": (
        "In use today, even if limited in scope.",
        (
            "the company's own use is stated as in operation, in the present or past tense (\"we use\", "
            "\"we have implemented\", \"is integrated into\")",
            "the use is described as operational, not as a trial or test only; limited scope does not matter",
        ),
    ),
    "unclear": (
        "Use is stated but the stage cannot be told.",
        (
            "the company's own use is asserted in a clause that is not a review or control remit (\"AI usage "
            "across our operations\" in a business description)",
            "the wording gives neither a tense nor a term that fits `planned`, `piloting` or `deployed`",
        ),
    ),
}

AI_KINDS: dict[str, Definition] = {
    "generative": (
        "Generative AI, LLMs, chatbots, copilots.",
        (
            "the passage names generative AI, large language models, chatbots, copilots, content-generating "
            "tools or a named product of that kind",
            "that AI is the one the roles refer to (the company's own use when `adoption` is a role)",
        ),
    ),
    "non_generative": (
        "Predictive or analytical machine learning, computer vision, optimisation.",
        (
            "the passage names machine learning, predictive analytics, computer vision, optimisation, "
            "recommendation, forecasting, automation or a similar non-generative technique",
            "that AI is the one the roles refer to (the company's own use when `adoption` is a role)",
            "no generative kind is named for the same actor (`generative` wins otherwise)",
        ),
    ),
    "unspecified": (
        "\"AI\" without further detail. Also the answer for `implicit` passages.",
        (
            "the passage names AI only generically, or (for `implicit`) not at all",
            "no technique or product that fits `generative` or `non_generative` is named for the actor the "
            "roles refer to",
        ),
    ),
}

DISCLOSURE_TRAITS: dict[str, Definition] = {
    "boilerplate": (
        "Generic language that could appear unchanged in any company's report.",
        (
            "no company-specific system, counterparty, figure, date or action",
            "no sector-specific mechanism",
            "the sentence would remain equally fitting in another company's report",
        ),
    ),
    "hedging": (
        "Uncertainty language that avoids commitment.",
        (
            "modal or conditional phrasing (may, could, potentially, no assurance)",
            "applied to the AI statement itself, not only to the general risk-factor frame",
            "no concrete scope, likelihood or mitigation given",
        ),
    ),
    "externalisation": (
        "Responsibility or origin of the AI risk is placed outside the company.",
        (
            "the AI and its risk are attributed to vendors, service providers, customers, developers or "
            "attackers (frame-dependent: evaluated only when the roles include `adoption`, `offering`, "
            "`governance` or `risk` and the frame is not `market`; in frame `market` the trait is not "
            "applicable and is never set)",
            "the company's own use or control is not stated",
            "no own mitigation is described",
        ),
    ),
    "vagueness": (
        "The AI referent is left undefined.",
        (
            "AI is named only as a category (\"emerging technologies such as AI\", \"AI tools\")",
            "no function, process or purpose is given",
            "no stage, scope or timeframe is given",
        ),
    ),
    "safe_harbour": (
        "The statement is framed to limit liability rather than to inform.",
        (
            "explicit forward-looking or cautionary framing tied to the AI statement",
            "disclaimer language (no assurance, cannot guarantee, not fully tested)",
            "the framing adds no information about the risk mechanism",
        ),
    ),
}

# Ordered from 1 (least) to 5 (most): every level includes what the level below requires.
SUBSTANTIVENESS: dict[str, Definition] = {
    "boilerplate": (
        "Level 1. A general statement that could appear unchanged in any company's report.",
        (
            "no area of the business, system, use case, counterparty, figure, date or action is named",
            "the sentence would remain equally fitting in another company's report",
        ),
    ),
    "generic": (
        "Level 2. Names an area the AI statement applies to, but nothing specific to the company.",
        (
            "an area is named (a function such as customer service, a kind of risk such as cybersecurity, "
            "a market)",
            "no concrete system, use case or mechanism of this company is named",
        ),
    ),
    "specific": (
        "Level 3. Names a concrete system, use case or mechanism of this company.",
        (
            "a named or described system, product, use case, counterparty or mechanism of effect that "
            "belongs to this company's own situation",
            "no concrete measure, responsibility or commitment is stated for it",
        ),
    ),
    "detailed": (
        "Level 4. As level 3, and states concrete measures, responsibilities or commitments.",
        (
            "meets the first criterion of `specific`",
            "states what the company does or has decided about it: a measure, mitigation, assigned "
            "responsibility, policy or commitment",
            "no verifiable figure, amount, date or realised outcome is given",
        ),
    ),
    "quantified": (
        "Level 5. As level 4, and gives verifiable particulars.",
        (
            "meets the first two criteria of `detailed`",
            "gives at least one verifiable particular about the AI statement: a figure, amount, date, "
            "share or an outcome that has occurred",
        ),
    ),
}
SUBSTANTIVENESS_LEVELS = {name: level for level, name in enumerate(SUBSTANTIVENESS, 1)}

Frame = Literal["risk_factor", "governance", "business", "market"]
Substantiveness = Literal["boilerplate", "generic", "specific", "detailed", "quantified"]
Role = Literal["market_driver", "adoption", "offering", "risk", "governance", "incident", "general"]
RiskType = Literal[
    "market_demand", "strategic_competitive", "operational_reliability", "cybersecurity",
    "third_party", "regulatory_legal", "workforce", "reputational_ethical",
    "information_integrity", "environmental", "other",
]
DisclosureTrait = Literal["boilerplate", "hedging", "externalisation", "vagueness", "safe_harbour"]


class Label(BaseModel):
    passage_id: str
    ai_reference: Literal["explicit", "implicit", "none"]
    frame: Optional[Frame] = None  # required when the passage is about AI; decided before the roles
    roles: list[Role] = Field(default_factory=list)
    risk_types: list[RiskType] = Field(default_factory=list)
    adoption_stage: Optional[Literal["planned", "piloting", "deployed", "unclear"]] = None
    ai_kind: Optional[Literal["generative", "non_generative", "unspecified"]] = None
    disclosure_traits: list[DisclosureTrait] = Field(default_factory=list)
    substantiveness: Optional[Substantiveness] = None  # required when the passage is about AI
    entities: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> "Label":
        if self.ai_reference == "none":
            filled = (
                self.frame or self.roles or self.risk_types or self.adoption_stage or self.ai_kind
                or self.disclosure_traits or self.substantiveness or self.evidence
            )
            if filled:
                raise ValueError("ai_reference 'none' must leave all other label fields empty")
            return self
        if self.frame is None:
            raise ValueError("frame is required when the passage is about AI")
        if not self.roles:
            raise ValueError("at least one role is required when the passage is about AI")
        if "general" in self.roles and len(self.roles) > 1:
            raise ValueError("'general' cannot be combined with other roles")
        if bool(self.risk_types) != ("risk" in self.roles):
            raise ValueError("risk_types must be given if and only if 'risk' is among the roles")
        if (self.adoption_stage is not None) != ("adoption" in self.roles):
            raise ValueError("adoption_stage must be given if and only if 'adoption' is among the roles")
        if "externalisation" in self.disclosure_traits and self.frame == "market":
            raise ValueError("'externalisation' is not applicable in frame 'market'")
        if self.ai_kind is None or not self.evidence:
            raise ValueError("ai_kind and evidence are required when the passage is about AI")
        if self.substantiveness is None:
            raise ValueError("substantiveness is required when the passage is about AI")
        if len(self.evidence) > 3 or any(not q.strip() for q in self.evidence):
            raise ValueError("evidence must be a list of 1 to 3 non-empty quotes")
        return self


def _table(
    title: str, field: str, rule: str, values: dict[str, Definition], decisions: tuple[str, ...] = ()
) -> str:
    rows = "\n".join(
        f"- `{k}`: {definition}\n  Criteria (all required): "
        + "; ".join(f"({i}) {c}" for i, c in enumerate(criteria, 1))
        + "."
        for k, (definition, criteria) in values.items()
    )
    out = f"### {title} (`{field}`)\n{rule}\n\n{rows}\n"
    if decisions:
        out += "\nDecision rules:\n" + "\n".join(f"- {d}" for d in decisions) + "\n"
    return out


def codebook() -> str:
    """Coding instructions, rendered from the definitions above."""
    return "\n".join(
        [
            f"# Codebook: AI in corporate reports (taxonomy v{TAXONOMY_VERSION})",
            "",
            "You label passages from company filings. Each task is one passage: one or more paragraphs "
            "around a keyword hit, with the company, form, fiscal year, report section and nearest heading. "
            "Label what the passage itself says. Do not use outside knowledge about the company, and do not "
            "carry assumptions over from other passages. Ignore page numbers, \"Table of Contents\" lines, "
            "running headers and a heading of the following section that may trail the passage. "
            "A value applies only if all its criteria hold. The frame is fixed first: once you have decided "
            "whether the passage is about AI, determine the frame of the AI statement (Step 1) before you "
            "judge any role or trait; criteria marked \"frame-dependent\" are read in that frame.",
            "",
            "Return exactly one JSON object per passage, one per line (JSONL), with these fields:",
            "",
            _table(
                "Is the passage about AI?", "ai_reference",
                "Exactly one value, judged from the passage alone: not from other passages, and not from "
                "outside knowledge about the company.",
                AI_REFERENCE,
            ),
            "If `ai_reference` is `none`: set `roles`, `risk_types`, `disclosure_traits`, `entities` and "
            "`evidence` to `[]`, leave `frame`, `adoption_stage`, `ai_kind` and `substantiveness` as `null`, and still give "
            "`confidence`; `note` may still be used.\n",
            _table(
                "Step 1: determine the frame", "frame",
                "Exactly one value per passage, chosen for the AI statement that carries the labels. Decide it "
                "from the report section, the nearest heading and the function of the sentence (does it state "
                "a harm, describe an oversight remit, describe the company's own business, or describe a "
                "market?) BEFORE any role or trait is judged. `null` if and only if `ai_reference` is `none`. "
                "Criteria marked \"frame-dependent\" in the fields below are read in this frame.",
                FRAMES,
                decisions=(
                    "Order of tests: a sentence that states a possible harm is `risk_factor`; otherwise a "
                    "sentence that describes an oversight remit is `governance`; otherwise a sentence about "
                    "demand, prices, supply or investment is `market`; otherwise `business`.",
                    "Section and heading set the default (a risk-factor section is `risk_factor`; a board "
                    "oversight, risk management or cybersecurity governance heading is `governance`; Business "
                    "or MD&A is `business` or `market`); the function of the sentence overrides the default.",
                    "Several AI statements with different functions in one passage: take the frame of the "
                    "statement the labels rest on (the one your first `evidence` quote is taken from).",
                ),
            ),
            _table(
                "What role does AI play for the company?", "roles",
                "One or more values. `general` only alone. A risk-factor heading or sentence that says an "
                "AI-driven market may not develop is both `market_driver` and `risk`.",
                ROLES,
                decisions=(
                    "`adoption` counts only when the company states its own use or intention. A possibility "
                    "voiced only inside a risk statement (\"use of AI may expose us\") is not adoption. "
                    "Frame-dependent: in frame `governance`, \"AI usage\" named inside a review or control "
                    "remit (\"our evaluation reviews AI usage\") is `governance` only; `adoption` applies only "
                    "if a clause outside the governance remit asserts the company's own use or intention.",
                    "`governance`: AI named as an item inside a broader control, review or committee remit "
                    "counts as governance (usually with the `vagueness` trait); no AI-specific policy is "
                    "required. Frame-dependent: the role applies in any frame if its criteria hold; in frame "
                    "`governance` it is the primary role, and other roles are added only for clauses outside "
                    "the remit that meet their own criteria.",
                    "`market_driver` is frame-dependent: in frame `market` it is the primary role; in any "
                    "other frame it requires an explicit demand, price or supply statement in the passage.",
                ),
            ),
            _table(
                "Which risk?", "risk_types",
                "One or more values if and only if `risk` is among the roles; otherwise `[]`. Only risks the "
                "text attributes to AI. AI and a generic risk in neighbouring sentences without a link is not an AI risk.",
                RISK_TYPES,
                decisions=(
                    "Risks borne by third parties (customers, project developers) that reach the company only "
                    "through demand are `market_demand`, not the third party's risk type.",
                    "Code risk types by mechanism, not by consequence: \"poses risks to our reputation\" alone "
                    "does not give `reputational_ethical`; that type needs trust, fairness or ethics content.",
                    "Manipulation or poisoning of training data by an attacker is `cybersecurity`; wrong or "
                    "biased outputs are `operational_reliability`; both when both are stated.",
                ),
            ),
            _table(
                "How far is the company's own use?", "adoption_stage",
                "Exactly one value if and only if `adoption` is among the roles; otherwise `null`. "
                "If several stages are stated, give the most advanced one.",
                ADOPTION_STAGES,
            ),
            _table(
                "What kind of AI?", "ai_kind",
                "Exactly one value. It describes the AI the roles refer to; if `adoption` is among the roles, "
                "it describes the company's OWN use. AI attributed only to vendors, customers or attackers does "
                "not make the company's use generative. `generative` wins if both kinds appear for the same "
                "actor. For `implicit` passages give `unspecified`.",
                AI_KINDS,
            ),
            _table(
                "Which disclosure traits does the AI statement show?", "disclosure_traits",
                "Zero or more values when `ai_reference` is `explicit` or `implicit`; `[]` when it is `none`. "
                "Judged on the AI-related statements of the passage: a trait applies if any AI-related "
                "statement meets all its criteria. `[]` means none of the traits apply: the statement is "
                "specific, it names systems, counterparties, products, figures, dates or actions. "
                "`externalisation` is frame-dependent: evaluate it only when the roles include `adoption`, "
                "`offering`, `governance` or `risk` and the frame is not `market`; in frame `market` it is not "
                "applicable and is never set.",
                DISCLOSURE_TRAITS,
            ),
            _table(
                "How substantive is the AI statement?", "substantiveness",
                "Exactly one value when `ai_reference` is `explicit` or `implicit`; `null` when it is `none`. "
                "Five levels, ordered from 1 (`boilerplate`) to 5 (`quantified`). Judged on the AI-related "
                "statements of the passage as a whole: give the highest level whose criteria they meet. "
                "Particulars that are not about AI (the company's revenue, the date of the report) do not "
                "count.",
                SUBSTANTIVENESS,
            ),
            "### Other fields",
            "- `passage_id`: copied from the task.",
            "- `entities`: organisations or AI products the passage names in connection with AI "
            "(e.g. `[\"Microsoft\", \"Nvidia\"]`); `[]` if none. Allowed for `implicit` passages; `[]` for "
            "`none` passages. Not the reporting company itself, not sources of statistics.",
            "- `evidence`: a list of 1 to 3 quotes copied verbatim from the passage that support your labels, "
            "one per role where the roles rest on different sentences (each quote is checked as an exact "
            "substring, whitespace aside; do not paraphrase, do not add ellipses). `[]` if and only if "
            "`ai_reference` is `none`.",
            "- `confidence`: `low`, `medium` or `high` for the label as a whole.",
            "- `note`: optional, at most one sentence; `\"\"` or omitted when there is nothing to say. Use it "
            "when the taxonomy does not fit the passage; allowed for `none` passages too.",
            "",
        ]
    )
