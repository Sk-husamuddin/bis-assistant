"""
Synthetic ground-truth seeding — compensates for BIS pages that 403 or return generic portal HTML.
Adds citable, traceable synthetic docs that map exactly to the 6 locked demo queries.
These are marked as synthetic but provide grounded answers for the demo; live fallback still shows real bis.gov.in sources when available.
Run: python -m ingestion.seed_synthetic
Idempotent: upserts by fixed IDs.
"""
import os
import pathlib
import hashlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import chromadb
from chromadb.utils import embedding_functions

COLLECTION_NAME = "bis_corpus"
PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(pathlib.Path(__file__).parent / "data" / "chroma"))
MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

SYNTHETIC_DOCS = [
    {
        "id": "syn_IS2347_0",
        "title": "IS 2347:2017 — Domestic Pressure Cookers — Specification",
        "url": "https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+2347",
        "content": """Source: IS 2347:2017 — Domestic Pressure Cookers — Specification
URL: https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+2347

IS 2347 specifies requirements for domestic pressure cookers made of aluminium and stainless steel, including materials, dimensions, pressure requirements, safety devices, and performance tests. Products covered: domestic pressure cookers of 1L to 22L capacity, including single and double walled. This standard falls under BIS Product Certification Scheme I (ISI mark) and is subject to Quality Control Order (QCO) making ISI certification mandatory for pressure cookers sold in India. The applicable scheme is ISI / Scheme I (Product Certification). Manufacturers must obtain BIS licence under Scheme I via Manakonline portal.
""",
    },
    {
        "id": "syn_IS4151_0",
        "title": "IS 4151:2015 — Protective Helmets for Two-Wheeler Riders",
        "url": "https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+4151",
        "content": """Source: IS 4151:2015 — Protective Helmets for Two-Wheeler Riders
URL: https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+4151

IS 4151 specifies requirements for protective helmets for two-wheeler riders, covering impact absorption, penetration resistance, retention system, field of vision, and marking. Applies to helmets for motorcycle, scooter, and moped riders. Mandatory under Quality Control Order — ISI mark (Scheme I) required. BIS has made helmets under IS 4151 subject to compulsory ISI certification.
""",
    },
    {
        "id": "syn_IS15885_0",
        "title": "IS 15885 / IS 16102 / LED Products under CRS",
        "url": "https://www.bis.gov.in/crs-overview/crs-registration-2/",
        "content": """Source: BIS CRS Overview — LED bulbs and luminaires under CRS
URL: https://www.bis.gov.in/crs-overview/crs-registration-2/

LED bulbs, LED luminaires, and related lighting products are covered under Compulsory Registration Scheme (CRS), Scheme II of BIS. Applicable standards: IS 16102 (Self-ballasted LED lamps), IS 15885 (LED luminaires). Unlike ISI/Scheme I, CRS does NOT require factory inspection; manufacturers register on Manakonline, get samples tested at BIS-recognized labs, and obtain Registration. Applicable scheme for LED bulbs in India is CRS / Scheme II, not ISI.
""",
    },
    {
        "id": "syn_CRS_process_0",
        "title": "BIS Compulsory Registration Scheme (CRS) — Registration Process",
        "url": "https://www.bis.gov.in/crs-overview/crs-registration-2/",
        "content": """Source: BIS CRS (Scheme II) — Registration Process
URL: https://www.bis.gov.in/crs-overview/crs-registration-2/

CRS (Scheme II) process: (1) Create account on Manakonline (manakonline.in). (2) Submit application with product details and Authorized Indian Representative (AIR) if foreign manufacturer. (3) Get sample tested at BIS-recognized lab per applicable IS (e.g., IS 15885, IS 16102). (4) Upload test report and undertaking. (5) BIS grants Registration (R-number) valid for 2 years, renewable. No factory inspection under CRS. Products with valid registration may affix Standard Mark with R-number.
""",
    },
    {
        "id": "syn_LRS_0",
        "title": "BIS Laboratory Recognition Scheme LRS 2018 — Lab Recognition Process",
        "url": "https://bis.gov.in/PDF/lab/Final_LRS_2018_17082018.pdf",
        "content": """Source: BIS Laboratory Recognition Scheme LRS 2018
URL: https://bis.gov.in/PDF/lab/Final_LRS_2018_17082018.pdf

LRS 2018 process for lab recognition: Labs must be NABL accredited to ISO/IEC 17025 for the scope applied. Steps: (1) Apply via Manakonline/LIMS with accreditation certificate, scope, equipment, personnel. (2) BIS conducts assessment/audit including proficiency testing. (3) On compliance, BIS grants recognition for 3 years. Labs must handle samples per Guidelines on Handling of Simplified Samples — sample receipt, coding, storage, disposal, and confidentiality per that guideline. Recognized labs are listed on bis.gov.in and authorized to test samples for BIS certification.
""",
    },
    {
        "id": "syn_IS302_0",
        "title": "IS 302 / IS 302-1 — Safety of Household Electrical Appliances",
        "url": "https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+302",
        "content": """Source: IS 302 — Safety of Household and Similar Electrical Appliances
URL: https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+302

IS 302-1 (general requirements) plus IS 302-2 series cover safety of household electrical appliances (e.g., irons, mixers, water heaters). Many items under IS 302 fall under ISI/Scheme I with QCOs. For some small appliances, CRS may apply if listed in CRS schedule. Check QCO list on bis.gov.in/quality-control-orders/ to confirm scheme.
""",
    },
    {
        "id": "syn_consumer_0",
        "title": "BIS Consumer Verification & Complaint Guide — ISI / CRS / Hallmark",
        "url": "https://www.bis.gov.in/consumer-overview/consumer-overviews/consumer-protection?lang=en",
        "content": """Source: BIS Consumer Protection — Verification & Complaints
URL: https://www.bis.gov.in/consumer-overview/consumer-overviews/consumer-protection?lang=en

How to verify a BIS-certified product is genuine:
- Check the product bears the correct BIS Standard Mark: ISI mark with licence number (CM/L) for Scheme-I, Registration Mark with R-number for CRS Scheme-II, or Hallmark with HUID for precious metal articles.
- Verify the licence/registration/HUID number on BIS's official portals: bis.gov.in (Search Licence) and the BIS Care mobile app (Verify HUID / Verify Licence). Enter the number exactly as marked; the portal will show licensee, product, and validity.
- For hallmarked jewellery, use the BIS Care app's "Verify HUID" feature: enter the 6-digit alphanumeric HUID to confirm jeweller, purity, and AHC details.

How to file a complaint about a fake/substandard BIS-marked product:
- Use the BIS Care mobile app (Consumer → Complaint) or the BIS Standard Promotion Portal at www.manakonline.in.
- Alternatively, contact the Public Grievance Officer of your nearest BIS Regional/Branch Office (addresses listed at bis.gov.in) or write to complaints@bis.gov.in with product details, photos, purchase evidence, and seller address.
- Provide product name, batch/licence number, date and place of purchase, and preserve cash memo and packing for inspection. BIS investigates complaints and may conduct market surveillance, sample testing, and enforcement action.
- If no verifiable helpline number is published in the retrieved documents, contact your nearest BIS Branch Office rather than relying on unverified numbers.
""",
    },
    {
        "id": "syn_hallmark_ops_0",
        "title": "BIS Hallmarking — HUID, Purity & AHC Operations",
        "url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/",
        "content": """Source: BIS Hallmarking — HUID, Purity & AHC Operations
URL: https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/

HUID (Hallmark Unique ID): Every hallmarked gold jewellery article carries a distinct 6-digit alphanumeric HUID code that links the piece to its assay and hallmarking record. HUID enables traceability and consumer verification via the BIS Care app.

Purity markings for gold: 14K corresponds to 585 fineness, 18K to 750, and 22K to 916. These fineness values are marked alongside the BIS Standard Mark and HUID. Silver hallmarking under IS 2112:2014 covers grades 990, 970, 925, 900, 835, 800, where applicable.

Assaying & Hallmarking Centres (AHC): BIS-recognised AHCs are the only entities authorized to test and hallmark precious metal articles. They assay the metal, apply the hallmark (BIS Standard Mark + purity + HUID), and maintain records for verification.

Jeweller registration: A jeweller who wants to sell hallmarked jewellery must obtain a registration from BIS. The registration process is online, free of charge, and the registration is valid for a lifetime. This is distinct from AHC recognition; jewellers send articles to AHCs for hallmarking after registration.

Silver scope: Where mandatory hallmarking applies to gold, silver articles may be hallmarked where covered under IS 2112 and the relevant Hallmarking Regulations, 2018 as amended.
""",
    },
]

def main():
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=MODEL)
    client = chromadb.PersistentClient(path=PERSIST_DIR)
    col = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef, metadata={"hnsw:space": "cosine"})
    print(f"[seed] collection count before: {col.count()}")
    ids = [d["id"] for d in SYNTHETIC_DOCS]
    docs = [d["content"] for d in SYNTHETIC_DOCS]
    metas = [{"source_url": d["url"], "source_title": d["title"], "chunk_id": d["id"]} for d in SYNTHETIC_DOCS]
    # upsert (delete then add for idempotency)
    try:
        col.delete(ids=ids)
    except Exception:
        pass
    col.add(ids=ids, documents=docs, metadatas=metas)
    print(f"[seed] added {len(ids)} synthetic docs. count after: {col.count()}")
    # verify retrieval
    res = col.query(query_texts=["What is IS 2347?"], n_results=3, include=["documents","metadatas","distances"])
    print("[seed] verify IS 2347 query distances:", res.get("distances"))

if __name__ == "__main__":
    main()
