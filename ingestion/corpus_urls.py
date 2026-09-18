"""
Corpus URLs — locked for demo queries (Q4 decision: predefine 10-15 IS standards matching rehearsal queries).
Demo queries that this corpus must cover:
1. IS 2347 pressure cookers -> standard_lookup / product_to_standard
2. IS 4151 helmets
3. Pressure cooker product_to_standard
4. LED bulbs -> CRS/Scheme II
5. CRS process -> scheme_process
6. LRS 2018 lab recognition -> lab_query
Source: implementation.md §5
"""
from dataclasses import dataclass

@dataclass
class Source:
    url: str
    title: str
    kind: str  # html | pdf

CORPUS: list[Source] = [
    # Core scheme docs (confirmed-real per spec)
    Source("https://www.bis.gov.in/system-certification-overview/systems-certification/?lang=en", "BIS Systems Certification Overview (MSCS)", "html"),
    Source("https://bis.gov.in/PDF/lab/Final_LRS_2018_17082018.pdf", "BIS Laboratory Recognition Scheme LRS 2018", "pdf"),
    Source("https://www.manakonline.in/MANAK/static/userManual/PC/Guidelines_on_Handling_of_Simplified_samples.pdf", "Guidelines on Handling of Simplified Samples (Manakonline)", "pdf"),
    # Official BIS scheme pages
    Source("https://www.bis.gov.in/product-certification-overview/product-certification-overview/", "BIS Product Certification (ISI / Scheme I) Overview", "html"),
    Source("https://www.bis.gov.in/crs-overview/crs-registration-2/", "BIS Compulsory Registration Scheme (CRS / Scheme II) Overview", "html"),
    Source("https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/", "BIS Hallmarking Overview", "html"),
    Source("https://www.bis.gov.in/fmcs-overview/fmcs-overview/", "BIS FMCS Overview (Foreign Manufacturers)", "html"),
    # Standards Clubs
    Source("https://www.bis.gov.in/wp-content/uploads/2021/06/Guidelines-for-Standards-Clubs.pdf", "BIS Guidelines for Standards Clubs", "pdf"),
    # Product-specific BIS resources — map directly to demo queries
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+2347", "IS 2347 — Pressure Cookers", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+4151", "IS 4151 — Protective Helmets", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+302", "IS 302 / IS 302-1 — Safety of Household Electrical Appliances", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+16046", "IS 16046 — Secondary Cells/Batteries / LED-related CRS", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+15885", "IS 15885 — LED Lamps / Luminaires (safety)", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+14625", "IS 14625 — LPG-related / Storage?", "html"),
    Source("https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+1652", "IS 1652 — Footwear / other consumer product example", "html"),
    # Fallback general listing to ensure scheme tables are captured even if individual IS pages 404
    Source("https://www.bis.gov.in/product-certification-licensing/product-certification-schemes/", "BIS Product Certification Schemes Listing", "html"),
    Source("https://www.bis.gov.in/quality-control-orders/", "BIS Quality Control Orders (QCOs) — maps products to mandatory certification", "html"),
]

CORPUS.extend([
    Source("https://www.bis.gov.in/wp-content/uploads/2020/12/BIS-Act-2016.pdf", "BIS Act, 2016", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2019/09/BIS_ROD_Order_12092019.pdf", "BIS Act 2016 — Removal of Difficulty Order, 2019", "pdf"),
    Source("https://www.bis.gov.in/PDF/bs/Act_Enforcement.pdf", "Enforcement of BIS Act, 2016", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2020/10/BIS-Rules-2018_amendments_Sep_15102020.pdf", "BIS Rules, 2018 (with amendments)", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2019/03/BIS_CA_12032019.pdf", "BIS (Conformity Assessment) Regulations, 2018", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2020/07/BIS-Advisory-Committees-Regulations-2018-incorp.-Amendments-up-to-June-2020.pdf", "BIS (Advisory Committees) Regulations, 2018", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2019/02/BIS-Hallmarking-Regulations-2018-Incorp.-Amdt-1.pdf", "BIS (Hallmarking) Regulations, 2018", "pdf"),
    Source("https://www.bis.gov.in/PDF/bs/DoCA_BIS_Hallmarking_Regulations_2018_Gazette_notification.pdf", "DoCA Notification — Precious Metal Hallmarking, 2018", "pdf"),
    Source("https://www.bis.gov.in/PDF/bs/BIS(Powers&Duties)Regulations_05092018.pdf", "BIS (Powers and Duties of Director General) Regulations, 2018", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2020/07/BIS_CA_Amendment_Regulations_2020.pdf", "BIS (Conformity Assessment) Amendment Regulations, 2020", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/02/BS_1_08022021.pdf", "BIS (Conformity Assessment) First Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/02/BS_08022021.pdf", "BIS (Conformity Assessment) Second Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/07/BIS_CA_Third_Amendment_Regulations_2021_Gazette.pdf", "BIS (Conformity Assessment) Third Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/08/BIS-CA-4th-Amendment-Regulations-2021-Gazette.pdf", "BIS (Conformity Assessment) Fourth Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/12/BIS-CA-5th-Amdt-Regulations-2021-Gazette.pdf", "BIS (Conformity Assessment) Fifth Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/12/BIS-CA-6th-Amendment-Regulations-2021-Gazette.pdf", "BIS (Conformity Assessment) Sixth Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2022/03/Scheme-10.pdf", "BIS (Conformity Assessment) Amendment Regulations, 2022", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2022/03/BIS-HM-Amdt-Regulations-2021-Gazette.pdf", "BIS (Hallmarking) Amendment Regulations, 2021", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2022/03/BIS-HM-Amendment-Regulations-2022-1.pdf", "BIS (Hallmarking) Amendment Regulations, 2022", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2023/06/Gazette-21.06.23-Printed-Final.pdf", "BIS (Conformity Assessment) Amendment Regulations, 2023", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2023/09/Gazette-14-September-2023.pdf", "BIS (Advisory Committees-Amendment) Regulations, 2023", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2024/03/BIS-CA-Regulations-Amendment-06March2024.pdf", "BIS (Conformity Assessment) Amendment Regulations, 2024", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2024/09/Gazette-Notification-Published-amendment-to-regulation-conformity-assesment.pdf", "BIS (Conformity Assessment) Regulations, 2024", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/03/Gazette-Notification-1.pdf", "Amendment to BIS (Conformity Assessment) Regulation, 2026", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/05/Gazette-Notification-28.04.26.pdf", "Corrigendum — Amendment to BIS (Conformity Assessment) Regulations, 2018, published Feb 2026", "pdf"),
])

CORPUS.extend([
    Source("https://www.bis.gov.in/wp-content/uploads/2021/07/Guidance-document-on-QCOs-Revised-1.pdf", "BIS Guidance Document on Quality Control Orders (QCOs)", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/02/GrantofLicence-Guidelines-25Feb2026.pdf", "BIS Guidelines for Grant of Licence (Scheme-I)", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2020/09/BIS-DGO-No.3ofYear2020.pdf", "BIS Additional Guidelines for Scheme-I", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/02/Dealing-WithNon-Conformity-Guidelines-25Feb2026.pdf", "BIS Guidelines for Dealing with Product Non-Conformity", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/02/Dealing-With-Unsatisfactory-Performance-Guidelines-25Feb2026.pdf", "BIS Guidelines for Dealing with Unsatisfactory Performance", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/05/Website-GuidelinesForChangeInScopeOfLicence_may.pdf", "BIS Guidelines for Change in Scope of Licence", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2025/03/RenewalGuidelines-WebsiteHosting.pdf", "BIS Guidelines for Renewal of Licence", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2025/07/Guidelines-Samples-Coding-Retesting.pdf", "BIS Guidelines for Retesting of Samples", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/02/FactorySurveillance-Guidelines-25Feb2026.pdf", "BIS Guidelines for Factory Surveillance", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2026/02/MarketSurveillance-Guidelines-25Feb2026.pdf", "BIS Guidelines for Market Surveillance", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2023/07/GuidelinesForUtilisationOfClusterLabByMSMEs.pdf", "BIS Guidelines for Cluster-Based Test Facility Use by MSMEs", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2021/03/Grant-of-CoC-Guidelines.pdf", "BIS Scheme-IV Grant of Certificate of Conformity Guidelines", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2022/01/Guidelines-RenewalOf-CoC.pdf", "BIS Guidelines for Renewal of Certificate of Conformity", "pdf"),
    Source("https://www.bis.gov.in/wp-content/uploads/2020/12/brief-on-Hallmarking.pdf", "BIS Brief on Hallmarking", "pdf"),
])

CORPUS.extend([
    Source("https://www.bis.gov.in/consumer-overview/consumer-overviews/consumer-protection?lang=en", "BIS Consumer Protection — Complaints & BIS Care App (Consumer Overview)", "html"),
])

# Exact 5-6 rehearsal queries corpus is sized for
DEMO_QUERIES: list[dict] = [
    {"query": "What is IS 2347 and which products does it cover?", "type": "standard_lookup"},
    {"query": "What does IS 4151 specify for helmets?", "type": "standard_lookup"},
    {"query": "I manufacture stainless steel pressure cookers — which BIS standard and scheme applies?", "type": "product_to_standard"},
    {"query": "I want to sell LED bulbs in India — do I need CRS or ISI?", "type": "product_to_standard"},
    {"query": "What is the process for CRS (Scheme II) registration?", "type": "scheme_process"},
    {"query": "How does a lab get BIS recognition under LRS 2018?", "type": "lab_query"},
]
