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

TAXONOMY_VERSION = "0.9"

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

# v0.7: a passage either treats AI or it does not. Passages found through context terms only
# (data centres, industry lingo, euphemisms) are context, not AI statements, and are not labelled.
AI_REFERENCE: dict[str, Definition] = {
    "explicit": (
        "The passage treats AI: it names AI or an AI-specific technique and says something about it.",
        (
            "a term for AI or an AI-specific technique appears, as listed in the matched terms (artificial "
            "intelligence, machine learning, generative AI, LLM, neural network, computer vision, ...)",
            "the term is used in its technology sense, not as part of an unrelated name, abbreviation or "
            "keyword false positive",
            "a statement is made about that AI for the company, its market or its risks; a word such as "
            "analytics, data science, automation, algorithm, digital, predictive or autonomous without an "
            "AI term is not enough, whatever it may stand for",
        ),
    ),
    "none": (
        "The passage does not treat AI.",
        (
            "no AI term is used in its technology sense, or the only AI term is a keyword false positive "
            "(an abbreviation, a product or company name, a word in an unrelated sense)",
            "nothing is said about AI for the company; descriptions of analytics, automation or algorithms "
            "that do not name AI are `none`",
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
            "AI is named as a cause of that demand or condition",
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
            "the passage is about AI (`explicit`)",
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
    "national_security": (
        "AI as a matter of national security, defence or state control over strategic technology.",
        (
            "the harm concerns national security, defence, critical infrastructure or a restriction a state "
            "imposes on security grounds (export controls, sanctions, foreign-investment review, procurement "
            "bans, restrictions on foreign-made AI or chips)",
            "AI or AI-linked technology (models, chips, compute, data) is the object or the cause of that "
            "concern or restriction",
            "the harm reaches the company: restricted sales or supply, lost contracts or licences, or "
            "obligations it must meet",
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

# v0.9: the MIT AI Risk Repository's Domain Taxonomy (7 domains, 24 subdomains; Slattery et al.,
# arXiv 2408.12622, Table 2; airisk.mit.edu/risks). The shared key for linking disclosures to the
# Repository, the Incident Tracker, the Delphi study and the Governance Map. Coded next to the
# firm-centric `risk_types`, from what the passage states, for passages with the role `risk` or
# `incident`. The value is the subdomain's number; `other` is the residual for stated harms the
# taxonomy lacks (what the residual holds is itself a research question).
MIT_SUBDOMAINS: dict[str, Definition] = {
    "unfair_discrimination_misrepresentation": (
        "1.1 Unfair discrimination and misrepresentation. Unequal treatment of individuals or groups "
        "by AI, often based on race, gender, or other sensitive characteristics, resulting in "
        "unfair outcomes and unfair representation of those groups.",
        (
            "the stated harm is unequal treatment, biased outcomes or misrepresentation of people"
            " or groups by an AI system",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "exposure_to_toxic_content": (
        "1.2 Exposure to toxic content. AI that exposes users to harmful, abusive, unsafe or "
        "inappropriate content, or provides advice or encourages action of that kind.",
        (
            "the stated harm is that users are shown or given harmful, abusive, unsafe or "
            "inappropriate content by an AI system",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "unequal_performance_across_groups": (
        "1.3 Unequal performance across groups. Accuracy and effectiveness of AI decisions and "
        "actions depend on group membership, through design decisions or biased training data.",
        (
            "the stated harm is that an AI system works worse for some groups than for others",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "compromise_of_privacy": (
        "2.1 Compromise of privacy by obtaining, leaking, or correctly inferring sensitive "
        "information. AI systems that memorize and leak sensitive personal data or infer private "
        "information without consent; unauthorized sharing of data that compromises privacy, "
        "assists identity theft or loses confidential intellectual property.",
        (
            "the stated harm is the leak, memorisation, inference or unauthorised use of personal"
            " data, confidential information or intellectual property through an AI system, "
            "including the company's own data entered into third-party AI tools",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "ai_system_security_vulnerabilities_attacks": (
        "2.2 AI system security vulnerabilities and attacks. Vulnerabilities in AI systems, software "
        "development toolchains and hardware that result in unauthorized access, data and privacy"
        " breaches, or system manipulation causing unsafe outputs or behavior.",
        (
            "the stated harm is that an AI system the company uses or offers is attacked, "
            "manipulated, poisoned or otherwise compromised (the AI is the target)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "false_or_misleading_information": (
        "3.1 False or misleading information. AI systems that inadvertently generate or spread "
        "incorrect or deceptive information, leading to inaccurate beliefs and to physical, "
        "emotional or material harms from decisions based on them.",
        (
            "the stated harm is that an AI system produces wrong, fabricated or misleading output"
            " that people or the company may act on (hallucination, inaccurate results)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "pollution_of_information_ecosystem": (
        "3.2 Pollution of information ecosystem and loss of consensus reality. Highly personalized "
        "AI-generated misinformation that creates filter bubbles, undermining shared reality and "
        "weakening social cohesion and political processes.",
        (
            "the stated harm is to the information environment as a whole (misinformation at "
            "scale, erosion of trust in information), not a single wrong output",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "disinformation_surveillance_influence": (
        "4.1 Disinformation, surveillance, and influence at scale. Using AI systems for large-scale "
        "disinformation campaigns, malicious surveillance, or automated censorship and propaganda"
        " to manipulate political processes, public opinion and behavior.",
        (
            "the stated harm involves an actor using AI for disinformation, surveillance, "
            "censorship or influence campaigns",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "cyberattacks_weapons_mass_harm": (
        "4.2 Cyberattacks, weapon development or use, and mass harm. Using AI systems to develop "
        "cyber weapons, to develop or enhance weapons, or to use weapons to cause mass harm.",
        (
            "the stated harm is an attacker's use of AI for cyberattacks, malware or weapons (AI "
            "is the attacker's tool against the company or others)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "fraud_scams_targeted_manipulation": (
        "4.3 Fraud, scams, and targeted manipulation. Using AI systems to gain a personal advantage "
        "over others through cheating, fraud, scams, blackmail, or targeted manipulation, "
        "including impersonation and synthetic imagery.",
        (
            "the stated harm is fraud, impersonation, deepfakes or scams carried out with AI "
            "against the company, its customers or its staff",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "overreliance_unsafe_use": (
        "5.1 Overreliance and unsafe use. Anthropomorphizing, trusting or relying on AI systems by "
        "users, leading to dependence, inappropriate expectations, exploitation of that trust, or"
        " harm from inappropriate use in critical situations.",
        (
            "the stated harm is that people (staff, customers, patients) rely on or use an AI "
            "system in a way that is unsafe or inappropriate, or trust its output too much",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "loss_of_human_agency_autonomy": (
        "5.2 Loss of human agency and autonomy. Delegation of key decisions to AI systems, or AI "
        "systems that make decisions that diminish human control and autonomy.",
        (
            "the stated harm is a loss of human control, oversight or autonomy because decisions "
            "are delegated to an AI system",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "power_centralization_unfair_benefits": (
        "6.1 Power centralization and unfair distribution of benefits. AI-driven concentration of "
        "power and resources within entities with access to or ownership of powerful AI, leading "
        "to inequitable distribution of benefits.",
        (
            "the stated harm is a concentration of power or benefits with the owners of AI "
            "(dependence on a few AI providers, market power, unequal access)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "inequality_decline_employment_quality": (
        "6.2 Increased inequality and decline in employment quality. Social and economic inequalities"
        " caused by widespread use of AI, such as automating jobs, reducing the quality of "
        "employment, or producing exploitative dependencies between workers and employers.",
        (
            "the stated harm concerns jobs, employment quality, skills or labour relations as a "
            "consequence of AI",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "devaluation_of_human_effort": (
        "6.3 Economic and cultural devaluation of human effort. AI creating economic or cultural "
        "value by reproducing human innovation or creativity, destabilizing systems that rely on "
        "human effort and disrupting creative and knowledge-based industries.",
        (
            "the stated harm is that AI-generated work substitutes or devalues human creative or "
            "knowledge work (content, art, code, research), including intellectual-property "
            "disputes over AI-generated or AI-trained material",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "ai_race_unsafe_deployment": (
        "6.4 Competitive dynamics. Competition by AI developers or state-like actors in an AI race, "
        "rapidly developing and deploying AI to maximize advantage, increasing the risk of "
        "releasing unsafe and error-prone systems.",
        (
            "the stated harm is that competitive pressure leads to rushed, unsafe or premature AI"
            " development or deployment (by the company or in its market)",
            "that competitors use AI and the company may fall behind, lose market share or fail to keep "
            "up is not this harm (it is `strategic_competitive` with `other`)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "regulation_lagging_behind_ai": (
        "6.5 Governance failure. Inadequate regulatory frameworks and oversight mechanisms that fail "
        "to keep pace with AI development, leading to ineffective governance and the inability to"
        " manage AI risks.",
        (
            "the stated harm is that rules, standards or oversight for AI are absent, unclear, "
            "lagging or inconsistent, so that AI risks go unmanaged",
            "that the company is subject to AI or data laws, must comply with them, or may face "
            "enforcement, liability or compliance cost is not this harm (it is `regulatory_legal` with "
            "`compromise_of_privacy`, `devaluation_of_human_effort` or `other`)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "environmental_harm": (
        "6.6 Environmental harm. The development and operation of AI systems that cause environmental"
        " harm, such as through energy consumption of data centers or the materials and carbon "
        "footprint of AI hardware.",
        (
            "the stated harm is energy, water, carbon or resource use of AI or its infrastructure",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "ai_pursuing_own_goals": (
        "7.1 AI pursuing its own goals in conflict with human goals or values. AI systems that act in"
        " conflict with ethical standards or human goals or values, including through misaligned "
        "behaviour such as manipulation, deception or power-seeking.",
        (
            "the stated harm is an AI system acting against the goals or values of its designers,"
            " users or society (misalignment, deception, unintended behaviour)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "ai_dangerous_capabilities": (
        "7.2 AI possessing dangerous capabilities. AI systems that develop, access, or are provided "
        "with capabilities that increase their potential to cause mass harm, such as deception, "
        "weapons development, cyber-offense, or self-proliferation.",
        (
            "the stated harm is that AI itself has or gains capabilities that could cause mass "
            "harm (frontier or dual-use capabilities), independent of a specific attacker",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "lack_of_capability_robustness": (
        "7.3 Lack of capability or robustness. AI systems that fail to perform reliably or "
        "effectively under varying conditions, exposing them to errors and failures with "
        "significant consequences.",
        (
            "the stated harm is that an AI system is unreliable, inaccurate, brittle or fails, in"
            " a sense other than wrong information for users (3.1) or unequal performance across "
            "groups (1.3)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "lack_of_transparency_interpretability": (
        "7.4 Lack of transparency or interpretability. Challenges in understanding or explaining the "
        "decision-making of AI systems, leading to mistrust, difficulty in enforcing compliance "
        "or holding actors accountable, and inability to identify and correct errors.",
        (
            "the stated harm is that AI decisions cannot be explained, audited or understood "
            "(black box, explainability, accountability)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "ai_welfare_and_rights": (
        "7.5 AI welfare and rights. Ethical considerations regarding the treatment of potentially "
        "sentient AI entities, including their potential rights and welfare.",
        (
            "the stated concern is the moral status, welfare or rights of AI systems themselves",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "multi_agent_risks": (
        "7.6 Multi-agent risks. Risks from multi-agent interactions due to incentives (conflict or "
        "collusion) or the structure of multi-agent systems, which can create cascading failures,"
        " selection pressures, new security vulnerabilities, and a lack of shared information and"
        " trust.",
        (
            "the stated harm arises from several AI systems or agents interacting (cascading "
            "failures, collusion, conflict, loss of control over agent systems)",
            "the passage states that harm as a risk to the company (`risk`) or as an event that "
            "occurred (`incident`), with AI as its cause or object",
        ),
    ),
    "other": (
        "A stated AI risk or incident that fits none of the 24 subdomains.",
        (
            "the `risk` or `incident` role applies",
            "no subdomain meets its criteria (firm-centric harms such as lost sales, lost "
            "competitiveness or compliance cost without a subdomain's mechanism)",
            "`note` names the harm",
        ),
    ),
}

# Where a firm-centric risk type usually lands in the Domain Taxonomy. Guidance for coders and the
# basis of a post-hoc approximation on labels without the field; it is this pipeline's reading,
# not a mapping published by MIT, and it never replaces coding from the passage.
RISK_TYPE_SUBDOMAINS: dict[str, tuple[str, ...]] = {
    "market_demand": ("other",),
    "strategic_competitive": ("other",),
    "operational_reliability": ("lack_of_capability_robustness", "false_or_misleading_information", "unfair_discrimination_misrepresentation", "unequal_performance_across_groups", "ai_pursuing_own_goals"),
    "cybersecurity": ("ai_system_security_vulnerabilities_attacks", "cyberattacks_weapons_mass_harm", "fraud_scams_targeted_manipulation"),
    "third_party": ("ai_system_security_vulnerabilities_attacks", "lack_of_capability_robustness", "power_centralization_unfair_benefits", "other"),
    "regulatory_legal": ("compromise_of_privacy", "devaluation_of_human_effort", "other"),
    "workforce": ("inequality_decline_employment_quality",),
    "reputational_ethical": ("unfair_discrimination_misrepresentation", "exposure_to_toxic_content", "overreliance_unsafe_use", "lack_of_transparency_interpretability"),
    "information_integrity": ("false_or_misleading_information", "pollution_of_information_ecosystem", "disinformation_surveillance_influence", "fraud_scams_targeted_manipulation"),
    "environmental": ("environmental_harm",),
    "national_security": ("cyberattacks_weapons_mass_harm", "disinformation_surveillance_influence", "power_centralization_unfair_benefits"),
    "other": ("other",),
}

# The Repository's numbering of the subdomains, for joins with MIT's datasets.
MIT_SUBDOMAIN_NUMBERS: dict[str, str] = {
    "unfair_discrimination_misrepresentation": "1.1",
    "exposure_to_toxic_content": "1.2",
    "unequal_performance_across_groups": "1.3",
    "compromise_of_privacy": "2.1",
    "ai_system_security_vulnerabilities_attacks": "2.2",
    "false_or_misleading_information": "3.1",
    "pollution_of_information_ecosystem": "3.2",
    "disinformation_surveillance_influence": "4.1",
    "cyberattacks_weapons_mass_harm": "4.2",
    "fraud_scams_targeted_manipulation": "4.3",
    "overreliance_unsafe_use": "5.1",
    "loss_of_human_agency_autonomy": "5.2",
    "power_centralization_unfair_benefits": "6.1",
    "inequality_decline_employment_quality": "6.2",
    "devaluation_of_human_effort": "6.3",
    "ai_race_unsafe_deployment": "6.4",
    "regulation_lagging_behind_ai": "6.5",
    "environmental_harm": "6.6",
    "ai_pursuing_own_goals": "7.1",
    "ai_dangerous_capabilities": "7.2",
    "lack_of_capability_robustness": "7.3",
    "lack_of_transparency_interpretability": "7.4",
    "ai_welfare_and_rights": "7.5",
    "multi_agent_risks": "7.6",
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

# v0.6: where in the business the company's own AI use sits.
BUSINESS_FUNCTIONS: dict[str, Definition] = {
    "customer_service": (
        "Customer support, service and communication with customers.",
        (
            "the company's own AI use is stated for customer support, service, contact centres or "
            "customer communication",
            "the AI handles or supports the contact with customers; winning or pricing business "
            "is `marketing_sales`",
        ),
    ),
    "marketing_sales": (
        "Marketing, advertising, sales, pricing and personalisation.",
        (
            "the company's own AI use is stated for marketing, advertising, sales, pricing, "
            "recommendations or personalisation",
            "the purpose is to win, target or price business, not to serve existing requests "
            "(`customer_service`)",
        ),
    ),
    "operations": (
        "Running the core business: service delivery, logistics, maintenance, scheduling.",
        (
            "the company's own AI use is stated for running its operations or delivering its "
            "service (scheduling, routing, maintenance, quality, claims or transaction handling)",
            "no narrower function in this list fits (`manufacturing`, `supply_chain`)",
        ),
    ),
    "finance": (
        "Finance, accounting, treasury, underwriting and credit decisions as an internal "
        "function.",
        (
            "the company's own AI use is stated for finance, accounting, forecasting, treasury, "
            "underwriting, credit or fraud detection",
            "it is the company's own financial work or decision; a product sold to clients is the "
            "role `offering`",
        ),
    ),
    "hr_workforce": (
        "Hiring, training, staffing and employee productivity.",
        (
            "the company's own AI use is stated for hiring, training, staffing, employee "
            "productivity or workforce management",
            "it concerns the company's own employees or candidates",
        ),
    ),
    "legal_compliance": (
        "Legal work, compliance, risk management and audit.",
        (
            "the company's own AI use is stated for legal work, regulatory compliance, risk "
            "management or audit",
            "AI is the tool used in that work; rules that apply to AI are the role `governance`, "
            "not this value",
        ),
    ),
    "rd_product": (
        "Research, development, engineering and design of products or services.",
        (
            "the company's own AI use is stated for research, development, engineering, design, "
            "software development or discovery",
            "the AI is a tool in that work; an AI capability sold to customers is the role "
            "`offering`, not a business function",
        ),
    ),
    "it_cybersecurity": (
        "Information technology and security of the company's own systems.",
        (
            "the company's own AI use is stated for its IT, infrastructure, threat detection or "
            "cybersecurity",
            "it concerns the company's own systems; AI in the hands of attackers is a risk, not "
            "adoption",
        ),
    ),
    "supply_chain": (
        "Procurement, inventory, demand planning and suppliers.",
        (
            "the company's own AI use is stated for procurement, inventory, demand planning, "
            "sourcing or supplier management",
            "it concerns the flow of goods or inputs to the company, not making them "
            "(`manufacturing`)",
        ),
    ),
    "manufacturing": (
        "Production of goods.",
        (
            "the company's own AI use is stated for production, plants, process control or "
            "factory automation",
            "it concerns making the goods, not buying or moving them (`supply_chain`)",
        ),
    ),
    "decision_analytics": (
        "Analytics and decision support across functions.",
        (
            "the company's own AI use is stated for analytics, insights, forecasting or decision "
            "support",
            "no single function in this list is named as where it is applied",
        ),
    ),
    "other": (
        "A function is named that fits none of the above.",
        (
            "the passage names where the company uses AI",
            "no other function meets its criteria",
            "`note` names the function",
        ),
    ),
    "not_stated": (
        "The company's own AI use is stated without saying where in the business.",
        (
            "the passage states the company's own use or intention (\"we use AI\", \"across our "
            "operations\", \"in our business\") without naming a function, process or purpose",
            "only alone: given next to a named function it is dropped on acceptance",
        ),
    ),
}

# v0.6: what the company reports doing to manage AI. Six groups of responses.
GOVERNANCE_RESPONSES: dict[str, Definition] = {
    "oversight_structure": (
        "Who is responsible: board or committee oversight, an AI governance body, a "
        "responsible-AI function, named accountability.",
        (
            "the passage names a body, function or person of the company that oversees or is "
            "accountable for AI (board, board committee, AI governance committee, management "
            "council, a named officer)",
            "AI is within what it oversees, as its subject or as an item in its remit",
        ),
    ),
    "policies_processes": (
        "Rules and procedures: AI policy, risk or impact assessment, approval of models or use "
        "cases, AI inventory.",
        (
            "the passage names a policy, standard, framework, assessment, review, approval step "
            "or inventory that applies to AI",
            "it is a rule or procedure, not a body (`oversight_structure`) and not a control on a "
            "system (`technical_controls`)",
        ),
    ),
    "technical_controls": (
        "Controls on the systems: testing, monitoring, human oversight, access, privacy and "
        "security controls, model validation.",
        (
            "the passage names a control applied to AI systems or their use: testing, validation, "
            "monitoring, human review of outputs, access restriction, privacy or security "
            "safeguards",
            "the control acts on the system, its data or its outputs",
        ),
    ),
    "third_party_controls": (
        "Controls on vendors: due diligence, contractual requirements, vendor monitoring.",
        (
            "the passage names a control the company applies to vendors, service providers or "
            "partners in respect of AI: due diligence, contract terms, assessment or monitoring",
            "it is the company's own measure towards that party, not the party's own control",
        ),
    ),
    "workforce_measures": (
        "Measures for employees: AI training, guidance on use, workforce transition programmes.",
        (
            "the passage names training, guidance, acceptable-use rules or transition programmes "
            "for the company's employees in respect of AI",
            "the measure is in place or decided; a risk that employees may misuse AI is not a "
            "measure",
        ),
    ),
    "transparency_accountability": (
        "Auditing, reporting, documentation, explainability, incident reporting.",
        (
            "the passage names auditing, internal or external reporting, documentation, "
            "explainability or incident reporting for AI",
            "it produces a record or account that others can check (auditors, the board, "
            "regulators, the public)",
        ),
    ),
    "other": (
        "A response to AI is named that fits none of the above.",
        (
            "the `governance` role applies",
            "no other response meets its criteria",
            "`note` names the response",
        ),
    ),
}

# v0.8: the kinds of AI a passage names, one or more. A kind is coded only when a term for it is
# in the passage; nothing is estimated from context, industry or product. `unspecified` is the
# answer for "AI" without further detail, and it stands alone.
AI_KINDS: dict[str, Definition] = {
    "traditional_ml": (
        "Machine learning other than generative models: predictive, analytical or optimising models that "
        "learn from data.",
        (
            "the passage names machine learning, deep learning, neural networks, reinforcement learning, a "
            "learning or trained algorithm, or a named predictive or analytical model",
            "no narrower kind in this list is named for the same term (vision, language, recommendation and "
            "agents have their own values)",
        ),
    ),
    "generative_llm": (
        "Generative AI, large language models, chatbots, copilots, content-generating tools.",
        (
            "the passage names generative AI, a large language model, a chatbot, a copilot, a "
            "content-generating tool or a named product of that kind (ChatGPT, Gemini, Claude, Copilot)",
            "that AI is the one the roles refer to (the company's own use when `adoption` is a role)",
        ),
    ),
    "computer_vision": (
        "Image, video or visual perception techniques.",
        (
            "the passage names computer vision, image or video recognition, image classification, object "
            "detection, facial recognition or another visual-perception technique",
            "that AI is the one the roles refer to",
        ),
    ),
    "nlp": (
        "Natural language processing other than a generative model: text or speech understanding.",
        (
            "the passage names natural language processing, speech recognition, text analysis, sentiment "
            "analysis, translation or another language-understanding technique by name",
            "a large language model or chatbot named without such a term is `generative_llm` only",
        ),
    ),
    "recommendation": (
        "Recommendation or personalisation systems.",
        (
            "the passage names a recommendation engine, system or algorithm, or a personalisation or ranking "
            "engine",
            "that AI is the one the roles refer to",
        ),
    ),
    "agentic": (
        "AI agents: systems that plan, act or complete tasks on their own.",
        (
            "the passage names AI agents, agentic AI, autonomous agents, or AI that takes actions or completes "
            "tasks on its own",
            "an autonomous vehicle, device or process named without an AI-agent term is not `agentic`",
        ),
    ),
    "other": (
        "A named kind or technique of AI that fits none of the above.",
        (
            "the passage names a kind or technique of AI (expert system, genetic algorithm, AI-driven "
            "robotics, quantum machine learning, ...)",
            "no other value in this list fits it",
            "`note` names it",
        ),
    ),
    "unspecified": (
        "\"AI\" without further detail.",
        (
            "the passage names AI only generically (AI, artificial intelligence, AI tools, AI technologies, "
            "AI capabilities)",
            "no term for a kind in this list appears for the actor the roles refer to",
            "only alone: given next to a named kind it is dropped on acceptance",
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
    "information_integrity", "environmental", "national_security", "other",
]
BusinessFunction = Literal[
    "customer_service", "marketing_sales", "operations", "finance", "hr_workforce", "legal_compliance",
    "rd_product", "it_cybersecurity", "supply_chain", "manufacturing", "decision_analytics", "other", "not_stated",
]
MitSubdomain = Literal[
    "unfair_discrimination_misrepresentation",
    "exposure_to_toxic_content",
    "unequal_performance_across_groups",
    "compromise_of_privacy",
    "ai_system_security_vulnerabilities_attacks",
    "false_or_misleading_information",
    "pollution_of_information_ecosystem",
    "disinformation_surveillance_influence",
    "cyberattacks_weapons_mass_harm",
    "fraud_scams_targeted_manipulation",
    "overreliance_unsafe_use",
    "loss_of_human_agency_autonomy",
    "power_centralization_unfair_benefits",
    "inequality_decline_employment_quality",
    "devaluation_of_human_effort",
    "ai_race_unsafe_deployment",
    "regulation_lagging_behind_ai",
    "environmental_harm",
    "ai_pursuing_own_goals",
    "ai_dangerous_capabilities",
    "lack_of_capability_robustness",
    "lack_of_transparency_interpretability",
    "ai_welfare_and_rights",
    "multi_agent_risks",
    "other",
]
AiKind = Literal[
    "traditional_ml", "generative_llm", "computer_vision", "nlp", "recommendation", "agentic", "other",
    "unspecified",
]
GovernanceResponse = Literal[
    "oversight_structure", "policies_processes", "technical_controls", "third_party_controls",
    "workforce_measures", "transparency_accountability", "other",
]
DisclosureTrait = Literal["boilerplate", "hedging", "externalisation", "vagueness", "safe_harbour"]


class Label(BaseModel):
    passage_id: str
    ai_reference: Literal["explicit", "none"]
    frame: Optional[Frame] = None  # required when the passage is about AI; decided before the roles
    roles: list[Role] = Field(default_factory=list)
    risk_types: list[RiskType] = Field(default_factory=list)
    mit_subdomains: list[MitSubdomain] = Field(default_factory=list)  # with role risk or incident
    adoption_stage: Optional[Literal["planned", "piloting", "deployed", "unclear"]] = None
    business_functions: list[BusinessFunction] = Field(default_factory=list)
    governance_responses: list[GovernanceResponse] = Field(default_factory=list)
    ai_kinds: list[AiKind] = Field(default_factory=list)  # one or more when the passage is about AI
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
                self.frame or self.roles or self.risk_types or self.mit_subdomains or self.adoption_stage or self.ai_kinds
                or self.business_functions or self.governance_responses
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
        if bool(self.mit_subdomains) != ("risk" in self.roles or "incident" in self.roles):
            raise ValueError("mit_subdomains must be given if and only if 'risk' or 'incident' is among the roles")
        if (self.adoption_stage is not None) != ("adoption" in self.roles):
            raise ValueError("adoption_stage must be given if and only if 'adoption' is among the roles")
        if bool(self.business_functions) != ("adoption" in self.roles):
            raise ValueError("business_functions must be given if and only if 'adoption' is among the roles")
        if "not_stated" in self.business_functions and len(self.business_functions) > 1:
            # A named function means the function is stated: the placeholder is dropped, not refused.
            self.business_functions = [f for f in self.business_functions if f != "not_stated"]
        if bool(self.governance_responses) != ("governance" in self.roles):
            raise ValueError("governance_responses must be given if and only if 'governance' is among the roles")
        if "externalisation" in self.disclosure_traits and self.frame == "market":
            raise ValueError("'externalisation' is not applicable in frame 'market'")
        if not self.ai_kinds or not self.evidence:
            raise ValueError("ai_kinds and evidence are required when the passage is about AI")
        if "unspecified" in self.ai_kinds and len(self.ai_kinds) > 1:
            # A named kind means the kind is specified: the placeholder is dropped, not refused.
            self.ai_kinds = [k for k in self.ai_kinds if k != "unspecified"]
        if self.substantiveness is None:
            raise ValueError("substantiveness is required when the passage is about AI")
        if any(not q.strip() for q in self.evidence):
            raise ValueError("evidence must be a list of 1 to 3 non-empty quotes")
        # More than three quotes: the label is complete, the list is too long. The first three are kept.
        self.evidence = self.evidence[:3]
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
                "outside knowledge about the company. Every task contains at least one matched AI term; your "
                "job is to decide whether the passage treats AI or the term is a false positive.",
                AI_REFERENCE,
            ),
            "If `ai_reference` is `none`: set `roles`, `risk_types`, `mit_subdomains`, `business_functions`, `governance_responses`, "
            "`ai_kinds`, `disclosure_traits`, `entities` and `evidence` to `[]`, leave `frame`, "
            "`adoption_stage` and `substantiveness` as `null`, and still give "
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
                    "A restriction imposed on security grounds (export controls on AI chips or models, "
                    "sanctions, procurement bans) is `national_security`; add `regulatory_legal` only when the "
                    "passage also states compliance costs, enforcement or liability for the company.",
                ),
            ),
            _table(
                "Which subdomains of the MIT AI Risk Repository?", "mit_subdomains",
                "One or more values if and only if `risk` or `incident` is among the roles; otherwise `[]`. "
                "Each value names a subdomain; its number is given in the definition. Code from the harm the passage states, not from the risk type you "
                "gave: a passage can carry one `risk_types` value and two subdomains, or a subdomain the risk type "
                "does not suggest. Firm-centric harms with no subdomain mechanism (lost sales, lost competitiveness, "
                "compliance cost as such) are `other`. Typical, not binding: "
                + "; ".join(f"`{k}` -> {', '.join(f'`{v}`' for v in vs)}" for k, vs in RISK_TYPE_SUBDOMAINS.items()) + ".",
                MIT_SUBDOMAINS,
            ),
            _table(
                "How far is the company's own use?", "adoption_stage",
                "Exactly one value if and only if `adoption` is among the roles; otherwise `null`. "
                "If several stages are stated, give the most advanced one.",
                ADOPTION_STAGES,
            ),
            _table(
                "Where in the business is AI used?", "business_functions",
                "One or more values if and only if `adoption` is among the roles; otherwise `[]`. It describes "
                "the company's OWN use: functions of vendors, customers or attackers do not count. Give every "
                "function the passage names; `not_stated` only alone, when no function, process or purpose is "
                "named. Do not infer a function from the company's industry.",
                BUSINESS_FUNCTIONS,
            ),
            _table(
                "What does the company do to manage AI?", "governance_responses",
                "One or more values if and only if `governance` is among the roles; otherwise `[]`. Give every "
                "response the passage names. Code only what the text supports: a broad statement of "
                "responsible AI names no control. AI named as an item inside a broader remit takes the value of "
                "that remit (a board or committee remit is `oversight_structure`; a risk review, programme or "
                "policy is `policies_processes`).",
                GOVERNANCE_RESPONSES,
            ),
            _table(
                "What kinds of AI?", "ai_kinds",
                "One or more values when `ai_reference` is `explicit`; `[]` when it is `none`. They describe "
                "the AI the roles refer to; if `adoption` is among the roles, the company's OWN use. A kind is "
                "coded only when a term for it is in the passage: give every kind named, and do not estimate a "
                "kind from the context, the industry, the product or the year. \"We want to use more AI in "
                "customer service\" is `unspecified`. AI attributed only to vendors, customers or attackers "
                "does not give the company's use a kind. `unspecified` only alone: once a kind is named, the AI is "
                "specified, and `unspecified` given next to it is dropped on acceptance.",
                AI_KINDS,
            ),
            _table(
                "Which disclosure traits does the AI statement show?", "disclosure_traits",
                "Zero or more values when `ai_reference` is `explicit`; `[]` when it is `none`. "
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
                "Exactly one value when `ai_reference` is `explicit`; `null` when it is `none`. "
                "Five levels, ordered from 1 (`boilerplate`) to 5 (`quantified`). Judged on the AI-related "
                "statements of the passage as a whole: give the highest level whose criteria they meet. "
                "Particulars that are not about AI (the company's revenue, the date of the report) do not "
                "count.",
                SUBSTANTIVENESS,
            ),
            "### Other fields",
            "- `passage_id`: copied from the task.",
            "- `entities`: organisations or AI products the passage names in connection with AI "
            "(e.g. `[\"Microsoft\", \"Nvidia\"]`); `[]` if none, and `[]` for `none` passages. Not the "
            "reporting company itself, not sources of statistics.",
            "- `evidence`: a list of 1 to 3 quotes copied verbatim from the passage that support your labels "
            "(more than 3 are cut to the first 3 on acceptance), "
            "one per role where the roles rest on different sentences (each quote is checked as an exact "
            "substring, whitespace aside; do not paraphrase, do not add ellipses). `[]` if and only if "
            "`ai_reference` is `none`.",
            "- `confidence`: `low`, `medium` or `high` for the label as a whole.",
            "- `note`: optional, at most one sentence; `\"\"` or omitted when there is nothing to say. Use it "
            "when the taxonomy does not fit the passage; allowed for `none` passages too.",
            "",
        ]
    )
