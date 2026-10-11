# AI/Tech Regulation Timeline: US, EU, China

As of 2026-10-11. Every row is checked against the cited primary source (VERIFIED) or marked UNVERIFIED where only secondary sources were available.

## 1. Bucket data

See `docs/us-2025h1-dataset.md` for the corpus. Bucket `gs://airo-filings-raw/`: 7,794 US 10-K filings (field `form`: 10-K 4,027, ARS 2,524, 10-K/A 453, 20-F 394, N-CSR 224, remainder smaller), filing_date 2025-01-02 to 2025-06-30, fiscal year 2024 for 6,298 filings, 4,743 unique CIKs.

Filings per month: Jan 224, Feb 1,955, Mar 2,736, Apr 2,300, May 408, Jun 171.

## 2. US: federal, Congress, states, export controls

| Date | Instrument | Effect | Primary source | Status |
|---|---|---|---|---|
| 2022-08-09 | CHIPS and Science Act, P.L. 117-167 (H.R. 4346) | $52.7B semiconductor manufacturing incentives + R&D | https://www.congress.gov/bill/117th-congress/house-bill/4346 | VERIFIED |
| 2022-10-07 | BIS rule: advanced computing + semiconductor manufacturing controls on PRC | First chip/SME export controls; phased effective 10-07/10-12/10-21 | https://www.bis.gov/press-release/commerce-implements-new-export-controls-advanced-computing-semiconductor-manufacturing-items-peoples | VERIFIED |
| 2023-01-26 | NIST AI RMF 1.0 | Voluntary AI risk framework | https://www.nist.gov/itl/ai-risk-management-framework | VERIFIED |
| 2023-07-05 | NYC Local Law 144 (AEDT) enforcement begins | Bias audits + notices for automated hiring tools | https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page | VERIFIED |
| 2023-07-26 | SEC cybersecurity disclosure rules (Reg S-K Item 106 / 10-K Item 1C; 8-K Item 1.05) | 10-K disclosure for FY ending on/after 2023-12-15; 8-K Item 1.05 from 2023-12-18 | https://www.sec.gov/newsroom/press-releases/2023-139 | VERIFIED |
| 2023-10-17 | BIS updated advanced-computing/SME rules + Entity List | Performance-density threshold; closes Oct-2022 gaps | https://beta.bis.gov/press-release/commerce-strengthens-restrictions-advanced-computing-semiconductors-semiconductor | VERIFIED |
| 2023-10-30 | EO 14110 Safe, Secure, and Trustworthy AI | Comprehensive federal AI directives | https://www.federalregister.gov/documents/2023/11/01/2023-24283/safe-secure-and-trustworthy-development-and-use-of-artificial-intelligence | VERIFIED |
| 2024-03-13 | Utah SB 149 AI Policy Act signed (effective 2024-05-01) | GenAI disclosure duties; Office of AI Policy | https://le.utah.gov/~2024/bills/static/SB0149.html | VERIFIED |
| 2024-03-28 | OMB M-24-10 | Agency AI governance/risk rules under EO 14110 | https://www.whitehouse.gov/wp-content/uploads/2024/03/M-24-10-Advancing-Governance-Innovation-and-Risk-Management-for-Agency-Use-of-Artificial-Intelligence.pdf | VERIFIED |
| 2024-05-17 | Colorado SB 24-205 signed | High-risk AI duties, originally from 2026-02-01 | https://leg.colorado.gov/bills/sb24-205 | VERIFIED |
| 2024-07-26 | NIST AI 600-1 GenAI Profile | GenAI companion to AI RMF | https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence | VERIFIED |
| 2024-08-09 | Illinois HB 3773 / P.A. 103-0804 signed (effective 2026-01-01) | AI discrimination + notice in employment (IHRA) | https://www.ilga.gov/Legislation/publicacts/view/103-0804 | VERIFIED |
| 2024-09-28 | California AB 2013 signed, ch. 817 (effective 2026-01-01) | GenAI training-data documentation | https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=202320240AB2013 | VERIFIED |
| 2024-09-29 | California SB 1047 vetoed | Frontier-model safety bill killed | https://www.gov.ca.gov/wp-content/uploads/2024/09/SB-1047-Veto-Message.pdf | VERIFIED |
| 2024-12-02 | BIS HBM + SME controls; 140 Entity List additions | Expanded China chip controls | https://www.bis.gov/press-release/commerce-strengthens-export-controls-restrict-chinas-capability-produce-advanced-semiconductors-military | VERIFIED |
| 2025-01-13 | BIS "Framework for AI Diffusion" IFR (published 2025-01-15, 90 FR 4544) | Effective 2025-01-13; compliance from 2025-05-15 | https://www.federalregister.gov/documents/2025/01/15/2025-00636/framework-for-artificial-intelligence-diffusion | VERIFIED |
| 2025-01-20 | EO 14148 Initial Rescissions | Revokes EO 14110 | https://www.whitehouse.gov/presidential-actions/2025/01/initial-rescissions-of-harmful-executive-orders-and-actions/ | VERIFIED |
| 2025-01-23 | EO 14179 Removing Barriers to American Leadership in AI | Orders AI Action Plan; OMB memo revisions | https://www.whitehouse.gov/presidential-actions/2025/01/removing-barriers-to-american-leadership-in-artificial-intelligence/ | VERIFIED |
| 2025-03-24 | Virginia HB 2094 vetoed (veto sustained 2025-04-01) | High-risk AI developer/deployer act fails | https://lis.virginia.gov/bill-details/20251/HB2094 | VERIFIED |
| 2025-04-03 | OMB M-25-21 and M-25-22 | Replace M-24-10/M-24-18; "high-impact AI" category | https://www.whitehouse.gov/releases/2025/04/white-house-releases-new-policies-on-federal-agency-ai-use-and-procurement/ | VERIFIED |
| 2025-04-09 | USG imposes license requirement on Nvidia H20 to China (indefinite 04-14; 8-K filed 04-15) | Up to $5.5B charge announced | https://www.sec.gov/Archives/edgar/data/1045810/000104581025000082/nvda-20250409.htm | VERIFIED |
| 2025-05-09 | NY FY26 budget (S3008C, ch. 58) adds GBL 349-a Algorithmic Pricing Disclosure; effective 2025-11-10 | Notice when price set by algorithm using personal data | https://www.nysenate.gov/legislation/bills/2025/S3008 | VERIFIED |
| 2025-05-13 | BIS announces rescission of AI Diffusion rule | Non-enforcement; new chip guidance | https://www.bis.gov/press-release/department-commerce-announces-rescission-biden-era-artificial-intelligence-diffusion-rule-strengthens | VERIFIED |
| 2025-05-19 | TAKE IT DOWN Act, P.L. 119-12 (S. 146) | Bans nonconsensual intimate images incl. deepfakes; 48-hr takedown | https://www.congress.gov/bill/119th-congress/senate-bill/146 | VERIFIED |
| 2025-06-22 | Texas HB 149 TRAIGA signed (effective 2026-01-01) | Use-based AI prohibitions; AG enforcement | https://capitol.texas.gov/BillLookup/History.aspx?LegSess=89R&Bill=HB149 | VERIFIED |
| 2025-07-01 | Senate adopts Blackburn Amdt. 2814, 99-1 (Roll Call 363) | Strips 10-yr state AI-law moratorium | https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00363.htm | VERIFIED |
| 2025-07-14 | Nvidia: USG "assured" H20 licenses will be granted (granted Aug 2025 per 10-Q) | Reversal of April restriction | https://blogs.nvidia.com/blog/nvidia-ceo-promotes-ai-in-dc-and-china/ | VERIFIED |
| 2025-07-18 | GENIUS Act, P.L. 119-27 (S. 1582) | Federal stablecoin regime | https://www.congress.gov/bill/119th-congress/senate-bill/1582 | VERIFIED |
| 2025-07-23 | America's AI Action Plan + EO 14318 (data-center permitting), EO 14319 (Preventing Woke AI), EO 14320 (AI exports) | 90+ federal actions; EOs published 2025-07-28 | https://www.whitehouse.gov/releases/2025/07/white-house-unveils-americas-ai-action-plan/ | VERIFIED |
| 2025-08-28 | Colorado SB 25B-004 signed | Delays SB 24-205 to 2026-06-30 | https://leg.colorado.gov/bills/sb25b-004 | VERIFIED |
| 2025-09-23 | CPPA announces OAL approval of ADMT/risk-assessment/cyber-audit regs (effective 2026-01-01; ADMT compliance 2027-01-01) | CCPA ADMT rules final | https://cppa.ca.gov/announcements/2025/20250923.html | VERIFIED |
| 2025-09-29 | California SB 53 TFAIA signed (effective 2026-01-01) | Frontier-developer frameworks, incident reports, whistleblowers | https://www.gov.ca.gov/2025/09/29/governor-newsom-signs-sb-53-advancing-californias-world-leading-artificial-intelligence-industry/ | VERIFIED |
| 2025-10-13 | California SB 243 companion chatbots signed | Disclosure + self-harm protocols; reporting from 2027-07-01 | https://www.gov.ca.gov/2025/10/13/governor-newsom-signs-bills-to-further-strengthen-californias-leadership-in-protecting-children-online/ | VERIFIED |
| 2025-12-11 | EO 14365 Ensuring a National Policy Framework for AI (published 2025-12-16) | DOJ AI Litigation Task Force; Commerce review of state laws; BEAD conditions | https://www.federalregister.gov/documents/2025/12/16/2025-23092/ensuring-a-national-policy-framework-for-artificial-intelligence | VERIFIED |
| 2025-12-11 | OMB M-26-04 Unbiased AI Principles | Implements EO 14319 in LLM procurement | https://www.whitehouse.gov/wp-content/uploads/2025/12/M-26-04-Increasing-Public-Trust-in-Artificial-Intelligence-Through-Unbiased-AI-Principles-1.pdf | VERIFIED |
| 2025-12-18 | FY2026 NDAA, P.L. 119-60 (S. 1071) | DoD AI governance (secs. 1512, 1532, 1533); DeepSeek ban; NSA AI security guidance | https://www.congress.gov/bill/119th-congress/senate-bill/1071 | VERIFIED |
| 2025-12-19 | New York RAISE Act signed (S6953B/A6453B, ch. 699) | Frontier-developer safety frameworks, 72-hr incident reports | https://www.governor.ny.gov/news/governor-hochul-signs-nation-leading-legislation-require-ai-frameworks-ai-frontier-models | VERIFIED |
| 2026-01-09 | AG memo establishing DOJ AI Litigation Task Force | Challenges to state AI laws | https://www.justice.gov/ag/media/1422986/dl?inline= | VERIFIED |
| 2026-03-17 | Washington SSB 5886 signed (ch. 69) | Personality rights cover forged digital likenesses | https://lawfilesext.leg.wa.gov/biennium/2025-26/Pdf/Bill%20Reports/Senate/5886-S%20SBR%20FBR%2026.pdf | VERIFIED |
| 2026-03-20 | White House National Policy Framework for AI: Legislative Recommendations | Non-binding call for uniform federal standard preempting state laws | https://www.whitehouse.gov/wp-content/uploads/2026/03/03.20.26-National-Policy-Framework-for-Artificial-Intelligence-Legislative-Recommendations.pdf | VERIFIED |
| 2026-03-24 | Washington HB 2225 (companion chatbots, eff. 2027-01-01) and HB 1170 (AI provenance/disclosure, eff. 2028-01-01) signed | Chatbot safeguards; latent disclosures | https://lawfilesext.leg.wa.gov/biennium/2025-26/Pdf/Bills/Session%20Laws/House/2225-S.SL.pdf | VERIFIED |
| 2026-03-27 | New York S8828 RAISE Act chapter amendment signed (ch. 96) | Repeals/replaces Art. 44-B; effective 2027-01-01 | https://www.nysenate.gov/legislation/bills/2025/S8828 | VERIFIED |
| 2026-03-31 | Oregon SB 1546 signed (ch. 85; eff. 2027-01-01) | AI companion disclosure + self-harm safeguards | https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orLaw0085.pdf | VERIFIED |
| 2026-05-07 | Minnesota HF 1606 signed (ch. 72; eff. 2026-08-01) | Bans access to "nudification" tools; $500k/violation | https://www.revisor.mn.gov/bills/94/2025/0/HF/1606/ | VERIFIED |
| 2026-05-13 | Public Citizen tracker: 30 states have election-deepfake laws (Maryland 30th) | State count citation | https://www.citizen.org/news/30-states-now-have-laws-to-regulate-election-deepfakes/ | VERIFIED |
| 2026-05-14 | Colorado SB 26-189 signed | Repeals/reenacts SB 24-205 as ADMT law; obligations from 2027-01-01 | https://leg.colorado.gov/bills/sb26-189 | VERIFIED |
| 2026-05-26 | Maryland SB 720 AI Ready Schools Act signed (ch. 634; eff. 2026-06-01) | K-12 AI guidance and coordinators | https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/sb0720?ys=2026RS | VERIFIED |
| 2026-05-27 | Connecticut SB 5 / P.A. 26-15 CART Act signed | Chatbot, employment-ADMT, AI-layoff notice rules | https://www.cga.ct.gov/asp/CGABillStatus/cgabillstatus.asp?selBillType=Bill&bill_num=SB5 | VERIFIED |
| 2026-06-02 | EO 14409 Promoting Advanced AI Innovation and Security (published 2026-06-05) | Voluntary pre-release frontier-model access; cyber clearinghouse; no licensing | https://www.federalregister.gov/documents/2026/06/05/2026-11415/promoting-advanced-artificial-intelligence-innovation-and-security | VERIFIED |
| 2026-06-04 | "Great American AI Act" discussion draft (Obernolte/Trahan) | 3-yr preemption of state AI-development laws; not introduced; no vote as of 2026-10 | secondary only | UNVERIFIED |
| 2026-06-05 | NSPM-11 AI in the National Security Enterprise | Rapid AI adoption across IC/DoD | https://www.whitehouse.gov/fact-sheets/2026/06/fact-sheet-president-donald-j-trump-signs-historic-directive-on-ai-in-the-national-security-enterprise/ | VERIFIED |
| 2026-06-24 | NO FAKES Act of 2026 (S. 4591, introduced 2026-05-20) placed on Senate calendar; not enacted | Digital-replica right | https://www.congress.gov/bill/119th-congress/senate-bill/4591 | VERIFIED |
| 2026-06-29 | House passes H.R. 7757 KIDS Act, 267-117; in Senate Commerce since 2026-07-13 | KOSA-derived provisions, AI chatbot disclosure to minors | https://www.congress.gov/bill/119th-congress/house-bill/7757/all-actions | VERIFIED |
| 2026-09-10 | California child-safety package signed (SB 1119 chatbots, SB 867 chatbot toys, AB 1709, AB 1856) | Minor protections for chatbots/platforms | https://www.gov.ca.gov/2026/09/10/governor-newsom-signs-the-strongest-child-safety-chatbot-and-social-media-laws-in-the-nation/ | VERIFIED |
| 2026-09-18 | California EO N-9-26 | Independent AI oversight; frontier "kill switch" | https://www.gov.ca.gov/2026/09/18/governor-newsom-issues-executive-order-to-accelerate-independent-oversight-and-advance-the-creation-of-an-ai-kill-switch/ | VERIFIED |
| 2026-09-29 | EO 14434 Inaugurating the Era of Super Intelligence (published 2026-10-02) | Executive branch to use "Super Intelligence/SI" in place of "AI" | https://www.federalregister.gov/documents/2026/10/02/2026-20321/inaugurating-the-era-of-super-intelligence | VERIFIED |
| 2026-09-30 | Sen. Paul blocks KOSA unanimous consent | Senate KOSA stalled | secondary only | UNVERIFIED |

## 3. US: agencies and courts

| Date | Actor / instrument | Effect | Primary source | Status |
|---|---|---|---|---|
| 2023-05-18 | EEOC technical assistance on AI in employment selection (Title VII) | Disparate-impact rules apply to algorithmic selection tools | https://www.eeoc.gov/history/eeoc-history-2020-2024 (original page now 404) | VERIFIED |
| 2023-07-26 | SEC final rule, cybersecurity disclosure (Rel. 33-11216) | 8-K Item 1.05 incident disclosure; Reg S-K Item 106 annual disclosure | https://www.sec.gov/newsroom/press-releases/2023-139 | VERIFIED |
| 2023-07-26 | SEC proposed rule, predictive data analytics conflicts (S7-12-23) | Broker-dealers/advisers to eliminate AI conflicts | https://www.sec.gov/newsroom/press-releases/2023-140 | VERIFIED |
| 2023-09-19 | CFPB Circular 2023-03, adverse action notices | Creditors using complex/AI models must give specific reasons | https://www.consumerfinance.gov/compliance/circulars/circular-2023-03-adverse-action-notification-requirements-and-the-proper-use-of-the-cfpbs-sample-forms-provided-in-regulation-b/ | VERIFIED (withdrawn 2025-05-12) |
| 2023-12-19 | FTC consent order, Rite Aid | 5-year ban on facial-recognition surveillance | https://www.ftc.gov/news-events/news/press-releases/2023/12/rite-aid-banned-using-ai-facial-recognition-after-ftc-says-retailer-deployed-technology-without | VERIFIED |
| 2024-02-08 | FCC Declaratory Ruling (FCC 24-17) | AI-cloned voices are "artificial" under TCPA | https://docs.fcc.gov/public/attachments/FCC-24-17A1.pdf | VERIFIED |
| 2024-03-18 | SEC settled actions, Delphia and Global Predictions | First "AI-washing" cases; $225k + $175k | https://www.sec.gov/newsroom/press-releases/2024-36 | VERIFIED |
| 2024-07-31 | US Copyright Office, Report Part 1: Digital Replicas | Recommends federal digital-replica right | https://www.copyright.gov/ai/ | VERIFIED |
| 2024-08-05 | US v. Google (D.D.C.), liability opinion, ECF 1033 | Section 2 liability in general search | https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0.pdf | VERIFIED |
| 2024-09-23 | DOJ Criminal Division, Evaluation of Corporate Compliance Programs (Sept 2024 update) | Prosecutors assess management of AI risk | https://www.justice.gov/criminal/criminal-fraud/page/file/937501/dl | VERIFIED |
| 2024-09-25 | FTC "Operation AI Comply" (DoNotPay, Rytr, Ascend Ecom, Ecommerce Empire Builders, FBA Machine) | Five actions over deceptive AI claims | https://www.ftc.gov/news-events/news/press-releases/2024/09/ftc-announces-crackdown-deceptive-ai-claims-schemes | VERIFIED |
| 2024-10-21 | SEC Division of Examinations, FY2025 Priorities | AI named as exam focus | https://www.sec.gov/newsroom/press-releases/2024-172 | VERIFIED |
| 2024-10-28 | Treasury, Outbound Investment Security Program final rule (EO 14105) | Restricts US investment in China-linked AI/semiconductors/quantum; effective 2025-01-02 | https://home.treasury.gov/news/press-releases/jy2687 | VERIFIED |
| 2024-12-18 | FTC final consent order, Rytr | Bars AI review-generation service | https://www.ftc.gov/news-events/news/press-releases/2024/12/ftc-approves-final-order-against-rytr-seller-ai-testimonial-review-service-providing-subscribers | VERIFIED |
| 2025-01-06 | FDA draft guidance, AI in drug/biologic regulatory decision-making | Risk-based credibility framework; still draft | https://www.fda.gov/news-events/press-announcements/fda-proposes-framework-advance-credibility-ai-models-used-drug-and-biological-product-submissions | VERIFIED |
| 2025-01-07 | FDA draft guidance, AI-Enabled Device Software Functions | Lifecycle recommendations; still draft | https://www.fda.gov/media/184856/download | VERIFIED |
| 2025-01-14 | SEC settled cease-and-desist, Presto Automation (Rel. 33-11352) | False statements about voice AI; no penalty | https://www.sec.gov/enforcement-litigation/administrative-proceedings/33-11352-s | VERIFIED |
| 2025-01-27 | EEOC removes AI technical assistance pages after EO 14179 | Guidance no longer posted | 404 confirmed; date from secondary sources | UNVERIFIED |
| 2025-01-29 | US Copyright Office, Report Part 2: Copyrightability | Human authorship required | https://www.copyright.gov/ai/ | VERIFIED |
| 2025-02-11 | FTC final order, DoNotPay | $193k relief; ban on unsubstantiated "robot lawyer" claims | https://www.ftc.gov/news-events/news/press-releases/2025/02/ftc-finalizes-order-donotpay-prohibits-deceptive-ai-lawyer-claims-imposes-monetary-relief-requires | VERIFIED |
| 2025-02-11 | Thomson Reuters v. Ross Intelligence (D. Del.) | Headnotes copyrightable; AI-training use not fair use | https://www.ded.uscourts.gov/sites/ded/files/opinions/20-613_5.pdf | VERIFIED |
| 2025-03-18 | Thaler v. Perlmutter (D.C. Cir.) | AI-generated work unregistrable | https://www.cadc.uscourts.gov/opinions/docs/2025/03/23-5233.pdf | VERIFIED |
| 2025-04-09 | SEC v. Saniger (Nate, Inc.), S.D.N.Y. complaint (LR-26282 dated 04-11) | Fraud for claiming AI when orders processed manually | https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26282 | VERIFIED |
| 2025-05-09 | US Copyright Office, Report Part 3: GenAI Training (pre-publication) | Training fair use case-by-case; market dilution relevant | https://www.copyright.gov/ai/ | VERIFIED |
| 2025-05-12 | CFPB withdrawal of 67 guidance documents (90 FR 20084) | Includes Circulars 2022-03 and 2023-03 on algorithms | https://www.federalregister.gov/documents/2025/05/12/2025-08286/interpretive-rules-policy-statements-and-advisory-opinions-withdrawal | VERIFIED |
| 2025-06-12 | SEC withdrawal of proposed rules (Rel. 33-11377) | Withdraws predictive-data-analytics proposal | https://www.sec.gov/rules-regulations/2025/06/s7-12-23 | VERIFIED |
| 2025-06-23 | Bartz v. Anthropic (N.D. Cal.), fair-use order, ECF 231 | Training on books fair use; pirated library copies not | https://storage.courtlistener.com/recap/gov.uscourts.cand.434709/gov.uscourts.cand.434709.231.0.pdf | VERIFIED |
| 2025-06-25 | Kadrey v. Meta (N.D. Cal.), summary judgment, ECF 598 | Llama training fair use on this record | https://storage.courtlistener.com/recap/gov.uscourts.cand.415175/gov.uscourts.cand.415175.598.0.pdf | VERIFIED |
| 2025-08-14 | Getty Images v. Stability AI refiled N.D. Cal. (3:25-cv-06891) | Pending | no primary document fetched | UNVERIFIED |
| 2025-08-28 | FTC final order vs Workado (AI-detector accuracy) | Accuracy claims substantiation | https://www.ftc.gov/news-events/news/press-releases/2025/08/ftc-approves-final-order-against-workado-llc-which-misrepresented-accuracy-its-artificial | VERIFIED |
| 2025-09-02 | US v. Google (D.D.C.), remedies opinion, ECF 1435 | Bans exclusive distribution deals incl. Gemini; no Chrome divestiture | https://www.justice.gov/opa/pr/department-justice-wins-significant-remedies-against-google | VERIFIED |
| 2025-09-11 | FTC 6(b) orders to Alphabet, Character.AI, Instagram, Meta, OpenAI, Snap, xAI | Companion-chatbot child-safety study | https://www.ftc.gov/news-events/news/press-releases/2025/09/ftc-launches-inquiry-ai-chatbots-acting-companions | VERIFIED |
| 2025-09-25 | Bartz v. Anthropic, preliminary approval of $1.5bn settlement | ~$3,000 per work | docket date only | UNVERIFIED |
| 2025-11-17 | SEC Division of Examinations, FY2026 Priorities | Does not name AI | https://www.sec.gov/newsroom/press-releases/2025-132-sec-division-examinations-announces-2026-priorities | VERIFIED |
| 2025-12-05 | US v. Google, final judgment, ECF 1462 | Remedies entered; on appeal | https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1462.0.pdf | VERIFIED |
| 2025-12-22 | FTC sets aside Rytr final order | Vacated per AI Action Plan | https://www.ftc.gov/news-events/news/press-releases/2025/12/ftc-reopens-sets-aside-rytr-final-order-response-trump-administrations-ai-action-plan | VERIFIED |
| 2026-01-05 | In re OpenAI Copyright Litigation (S.D.N.Y. MDL 3143) | 20m ChatGPT logs order; NYT v. OpenAI pending | order itself not retrieved | UNVERIFIED |
| 2026-01-13 | BIS revised license review policy for advanced chips (published 2026-01-15) | Case-by-case review of H200 / MI325X exports to China | https://www.bis.gov/press-release/department-commerce-revises-license-review-policy-semiconductors-exported-china | VERIFIED |
| 2026-03-02 | Supreme Court denies cert, Thaler v. Perlmutter (25-449) | Human-authorship ruling stands | https://www.supremecourt.gov/docket/docketfiles/html/public/25-449.html | VERIFIED |
| 2026-07-01 | FTC proposed Policy Statement on Suppression of Accuracy in AI Systems | Section 5 applies to distorted outputs; asserts preemption of conflicting state laws | https://www.ftc.gov/news-events/news/press-releases/2026/07/ftc-seeks-public-comment-policy-statement-addressing-ai-accuracy | VERIFIED |
| 2026-07-20 | Bartz v. Anthropic, final approval, ECF 680 | $1.5bn settlement final | https://storage.courtlistener.com/recap/gov.uscourts.cand.434709/gov.uscourts.cand.434709.680.0_5.pdf | VERIFIED |
| 2026-08-18 | FDA discussion paper on generative-AI-enabled devices (comments to 2026-10-19) | Regulatory approach consultation | https://www.fda.gov/news-events/press-announcements/fda-seeks-public-feedback-inform-regulatory-approach-generative-ai-enabled-medical-devices | VERIFIED |
| 2026-09-29 | Thomson Reuters v. Ross (3d Cir., precedential) | Affirms: AI-training copying by competitor not fair use | https://www2.ca3.uscourts.gov/opinarch/252153p.pdf | VERIFIED |

## 4. EU

| Date | Instrument | Effect | Primary source | Status |
|---|---|---|---|---|
| 2023-04-25 | DSA (Reg. 2022/2065) | First 17 VLOPs + 2 VLOSEs designated; compliance within four months | https://ec.europa.eu/commission/presscorner/detail/en/ip_23_2413 | VERIFIED |
| 2023-09-06 | DMA (Reg. 2022/1925) | Six gatekeepers designated | https://ec.europa.eu/commission/presscorner/detail/en/ip_23_4328 | VERIFIED |
| 2024-02-17 | DSA | Applies to all intermediaries/platforms | https://digital-strategy.ec.europa.eu/en/faqs/digital-services-act-questions-and-answers | VERIFIED |
| 2024-03-07 | DMA | Gatekeeper compliance deadline | https://ec.europa.eu/commission/presscorner/detail/en/ip_24_1342 | VERIFIED |
| 2024-07-12 | AI Act, Reg. (EU) 2024/1689 | Published in OJ L | https://eur-lex.europa.eu/eli/reg/2024/1689/oj | VERIFIED |
| 2024-08-01 | AI Act | Entry into force | https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689 | VERIFIED |
| 2024-09-05 | CoE Framework Convention on AI (CETS 225) | Opened for signature; EU, UK, US sign | https://digital-strategy.ec.europa.eu/en/news/commission-signs-council-europe-framework-convention-artificial-intelligence | VERIFIED |
| 2024-10-17 | NIS2 (Dir. 2022/2555) | Transposition deadline | https://digital-strategy.ec.europa.eu/en/policies/nis2-directive | VERIFIED |
| 2024-11-18 | Product Liability Directive (EU) 2024/2853 | Published in OJ; in force 2024-12-08 | https://eur-lex.europa.eu/eli/dir/2024/2853/oj | VERIFIED |
| 2024-12-10 | Cyber Resilience Act, Reg. (EU) 2024/2847 | Entry into force | https://eur-lex.europa.eu/eli/reg/2024/2847/oj | VERIFIED |
| 2025-01-17 | DORA, Reg. (EU) 2022/2554 | Applies (Art. 64) | https://eur-lex.europa.eu/eli/reg/2022/2554/oj | VERIFIED |
| 2025-02-02 | AI Act | Chapters I-II apply: prohibited practices (Art. 5) + AI literacy (Art. 4) | https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689 (Art. 113(a)) | VERIFIED |
| 2025-02-04 | Commission guidelines on prohibited practices | Non-binding Art. 5 guidance | https://digital-strategy.ec.europa.eu/en/library/commission-publishes-guidelines-prohibited-artificial-intelligence-ai-practices-defined-ai-act | VERIFIED |
| 2025-02-11 | Commission Work Programme 2025 | Announces withdrawal of AI Liability Directive proposal | https://commission.europa.eu/strategy-and-policy/strategy-documents/commission-work-programme/commission-work-programme-2025_en | VERIFIED |
| 2025-04-16 | CSRD "stop-the-clock" Directive (EU) 2025/794 | OJ publication; waves 2 and 3 postponed two years; CSDDD one year | https://eur-lex.europa.eu/eli/dir/2025/794/oj | VERIFIED |
| 2025 (FY2024) | CSRD wave 1 | First reports for FY2024 published in 2025 | https://finance.ec.europa.eu/capital-markets-union-and-financial-markets/company-reporting-and-auditing/company-reporting/corporate-sustainability-reporting_en | VERIFIED |
| 2025-07-10 | GPAI Code of Practice | Final Code published | https://digital-strategy.ec.europa.eu/en/news/general-purpose-ai-code-practice-now-available | VERIFIED |
| 2025-07-18 | Commission guidelines on GPAI providers (C(2025) 5045) | Scope of GPAI obligations | https://digital-strategy.ec.europa.eu/en/news/commission-publishes-guidelines-providers-general-purpose-ai-models | VERIFIED |
| 2025-08-02 | AI Act | GPAI obligations (Ch. V), governance, penalties apply (Art. 113(b)) | https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689 | VERIFIED |
| 2025-09-12 | Data Act, Reg. (EU) 2023/2854 | Applies (Art. 50) | https://eur-lex.europa.eu/eli/reg/2023/2854/oj | VERIFIED |
| 2025-10-06 | AI Liability Directive proposal | Formal withdrawal in OJ (C/2025/5423) | https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:52025XC05423 | VERIFIED |
| 2025-10-08 | Apply AI Strategy + AI in Science Strategy | Commission strategies, ~EUR 1 bn | https://commission.europa.eu/news-and-media/news/keeping-european-industry-and-science-forefront-ai-2025-10-08_en | VERIFIED |
| 2025-11-19 | Digital Omnibus package | Digital Omnibus (data/GDPR/cyber), Digital Omnibus on AI, Data Union Strategy | https://ec.europa.eu/commission/presscorner/detail/en/ip_25_2718 | VERIFIED |
| 2026-01-21 | Digital Networks Act proposal | Replacement of EECC proposed | https://commission.europa.eu/news-and-media/news/supporting-digital-connectivity-simpler-rules-2026-01-21_en | VERIFIED |
| 2026-04-21 | Council Decision (EU) 2026/1080 | EU concludes CoE Framework Convention on AI | https://eur-lex.europa.eu/eli/dec/2026/1080/oj/eng | VERIFIED |
| 2026-05-07 | Digital Omnibus on AI | Political agreement EP-Council | https://digital-strategy.ec.europa.eu/en/news/eu-agrees-simplify-ai-rules-boost-innovation-and-ban-nudification-apps-protect-citizens | VERIFIED |
| 2026-06-03 | Cloud and AI Development Act proposal (+ Chips Act 2.0) | Commission proposal | https://commission.europa.eu/news-and-media/news/strengthening-europes-tech-sovereignty-2026-06-03_en | VERIFIED |
| 2026-06-16 / 2026-06-29 | Digital Omnibus on AI | EP final vote / Council adoption | https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2025/0359(COD) | VERIFIED |
| 2026-07-24 | Digital Omnibus on AI, Reg. (EU) 2026/1744 (signed 2026-07-08) | OJ publication | https://eur-lex.europa.eu/eli/reg/2026/1744/oj | VERIFIED |
| 2026-07-27 | Reg. 2026/1744 | Entry into force; Annex III high-risk deferred to 2027-12-02, Annex I to 2028-08-02; Art. 50 not deferred; two new Art. 5 prohibitions from 2026-12-02 | https://eur-lex.europa.eu/eli/reg/2026/1744/oj | VERIFIED |
| 2026-08-02 | AI Act | General application: Art. 50 transparency, enforcement; high-risk deferred | https://commission.europa.eu/news-and-media/news/safer-and-more-transparent-ai-2026-08-02_en | VERIFIED |
| 2026-08-31 | DSA | ChatGPT designated VLOSE; Reddit, Roblox VLOPs | https://ec.europa.eu/commission/presscorner/detail/en/ip_26_1772 | VERIFIED |
| 2026-09-11 | CRA | Reporting obligations apply | https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act | VERIFIED |
| 2026-09-12 | Data Act Art. 3(1) | Access-by-design for new connected products | https://eur-lex.europa.eu/eli/reg/2023/2854/oj | VERIFIED |
| 2026-12-02 | AI Act (as amended) | New Art. 5 prohibitions (intimate imagery / CSAM) apply | https://eur-lex.europa.eu/eli/reg/2026/1744/oj | VERIFIED |
| 2026-12-09 | PLD 2024/2853 | Transposition deadline; applies to products placed on market after this date | https://eur-lex.europa.eu/eli/dir/2024/2853/oj | VERIFIED |
| 2027-12-02 | AI Act (as amended) | Annex III high-risk obligations apply | https://eur-lex.europa.eu/eli/reg/2026/1744/oj | VERIFIED |
| 2027-12-11 | CRA | Main obligations apply | https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act | VERIFIED |
| 2028-08-02 | AI Act (as amended) | Annex I / Art. 6(1) high-risk obligations apply | https://eur-lex.europa.eu/eli/reg/2026/1744/oj | VERIFIED |

Note: the two new Art. 5 prohibitions apply from 2026-12-02, not from entry into force. All other AI Act and Omnibus dates (2024-08-01, 2025-02-02, 2025-08-02, 2026-08-02, OJ 2026-07-24, in force 2026-07-27, 2027-12-02, 2028-08-02) match EUR-Lex.

## 5. China

| Date | Instrument | Effect | Source | Status |
|---|---|---|---|---|
| 2022-03-01 | Provisions on Algorithmic Recommendation Management (CAC, MIIT, MPS, SAMR; issued 2022-01-04) | Algorithm filing, transparency, minors/elderly protections | https://www.cac.gov.cn/2022-01/04/c_1642894606258238.htm | VERIFIED |
| 2023-01-10 | Provisions on Deep Synthesis Management (issued 2022-11-25) | Labeling, real-name, security assessment for deepfakes | https://www.cac.gov.cn/2022-12/11/c_1672221949354811.htm | VERIFIED |
| 2023-05-31 | State Council 2023 Legislative Work Plan | Lists AI Law draft for NPCSC review | https://www.gov.cn/zhengce/content/202306/content_6884925.htm | VERIFIED |
| 2023-08-15 | Interim Measures for Generative AI Services (issued 2023-07-13) | Security assessment and filing for public GenAI | https://www.cac.gov.cn/2023-07/13/c_1690898326795531.htm | VERIFIED |
| 2023-12-01 | Measures for Ethical Review of Science and Technology (Trial) | Mandatory ethics review for AI research | https://www.most.gov.cn/xxgk/xinxifenlei/fdzdgknr/fgzc/gfxwj/gfxwj2023/202310/t20231008_188309.html | VERIFIED |
| 2024-02-29 | TC260-003 Basic Security Requirements for GenAI Services | Corpus/model/security requirements for filing | https://www.tc260.org.cn/portal/article/2/20240301164054 | UNVERIFIED (portal post dated 2024-03-01) |
| 2024-05-06 | State Council 2024 Legislative Work Plan | Again lists AI Law draft | https://www.gov.cn/yaowen/liebiao/202405/content_6950151.htm | VERIFIED |
| 2024-09-09 | AI Safety Governance Framework 1.0 (TC260) | Non-binding risk taxonomy | https://www.cac.gov.cn/2024-09/09/c_1727567886199789.htm | VERIFIED |
| 2025-01-01 | Network Data Security Management Regulations (State Council Order 790; signed 2024-09-24) | Binding data-security regime incl. AI training data | https://www.gov.cn/zhengce/content/202409/content_6977766.htm | VERIFIED |
| 2025-02-28 | GB 45438-2025 Labeling method for AI-generated content (mandatory; effective 2025-09-01) | First mandatory AI national standard | https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=F32EA2A561F1886CD8D606513512D547 | VERIFIED |
| 2025-03-07 / published 2025-03-14 | Measures for Labeling AI-Generated Synthetic Content (effective 2025-09-01) | Mandatory explicit + implicit labeling | https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm | VERIFIED |
| 2025-04-25 | GB/T 45654-2025 Basic security requirements for GenAI services (effective 2025-11-01) | National-standard successor to TC260-003 | https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=F67D3F376E0A0A0FF5317FB36B32A30A | VERIFIED |
| 2025-05-14 | State Council 2025 Legislative Work Plan | No AI Law draft listed | https://www.gov.cn/yaowen/liebiao/202505/content_7023700.htm | VERIFIED |
| 2025-08-21 / published 2025-08-26 | State Council Opinions on "AI Plus" Action | Adoption targets 70% (2027), 90% (2030) | https://www.gov.cn/yaowen/liebiao/202508/content_7037868.htm | VERIFIED |
| 2025-09-15 | AI Safety Governance Framework 2.0 (TC260) | Revised risk classification | https://www.cac.gov.cn/2025-09/15/c_1759653448369123.htm | VERIFIED |
| 2025-10-28 | NPCSC Decision amending the Cybersecurity Law (effective 2026-01-01) | New Art. 20 on AI research, infrastructure, ethics, risk monitoring | http://www.npc.gov.cn/npc/c2/c30834/202510/t20251028_449048.html | VERIFIED |
| 2025-12-26 / published 2026-01-23 | Measures on Online Information Affecting Minors (effective 2026-03-01) | Art. 9 covers recommender and GenAI providers | https://www.cac.gov.cn/2026-01/23/c_1770728781060093.htm | VERIFIED |
| 2025-12-27 | Draft Interim Measures for AI Anthropomorphic Interactive Services | "AI companion" rules draft | https://www.cac.gov.cn/2025-12/27/c_1768571207311996.htm | VERIFIED |
| 2026-04-10 | Interim Measures for AI Anthropomorphic Interactive Services (CAC Order 21; effective 2026-07-15) | Bans virtual partner services to minors; anti-dependency duties | https://www.cac.gov.cn/2026-04/10/c_1777558395078289.htm | VERIFIED |
| 2026-05-08 | Implementation Opinions on AI Agents (CAC, NDRC, MIIT) | First national agent-specific instrument | https://www.cac.gov.cn/2026-05/08/c_1779979789738376.htm | VERIFIED |
| 2026-05-08 / published 2026-05-11 | State Council 2026 Legislative Work Plan | Calls for comprehensive AI legislation; no named AI Law draft | https://www.gov.cn/zhengce/content/202605/content_7068345.htm | VERIFIED |
| 2026-07-28 | SAC approves mandatory national standard plan for agent application security | Drafting stage | https://www.news.cn/tech/20260728/8ebf5083cf0e487287f894fb31e123f5/c.html | VERIFIED (Xinhua) |
| 2026-09-14 | AI Safety Governance Framework 3.0 (TC260) | Agent and embodied-AI risks as separate categories | https://www.cac.gov.cn/2026-09/17/c_1791397053329870.htm | VERIFIED |
| 2026-09-18 | Draft State Council Regulations on Minors' Safe Use of the Internet (comments to 2026-10-17) | Minors mode for cognition-affecting AI services | https://www.cac.gov.cn/2026-09/18/c_1791482017777471.htm | VERIFIED (draft) |

No AI Law had been submitted to the NPC Standing Committee as of 2026-10-11.
