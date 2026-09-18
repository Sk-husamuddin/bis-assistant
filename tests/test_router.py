import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import os
# force heuristic path (no GROQ key)
os.environ.pop("GROQ_API_KEY", None)

from agent.nodes.router import router_node

def route(q):
    return router_node({"query": q}).get("query_type")

# standard_lookup (4)
def test_router_standard_is_number():
    assert route("What is IS 2347 and which products does it cover?") == "standard_lookup"

def test_router_standard_is_4151():
    assert route("What does IS 4151 specify for helmets?") == "standard_lookup"

def test_router_standard_generic():
    assert route("Tell me about IS 302 for household electrical appliances") == "standard_lookup"

def test_router_standard_cover():
    assert route("Which products does IS 16046 cover?") == "standard_lookup"

# product_to_standard (3)
def test_router_product_pressure_cooker():
    assert route("I manufacture stainless steel pressure cookers — which BIS standard and scheme applies?") == "product_to_standard"

def test_router_product_led():
    assert route("I want to sell LED bulbs in India — do I need CRS or ISI?") == "product_to_standard"

def test_router_product_generic_sell():
    assert route("I want to sell power banks in India, what certification do I need?") == "product_to_standard"

# scheme_process (3)
def test_router_scheme_crs_process():
    assert route("What is the process for CRS (Scheme II) registration?") == "scheme_process"

def test_router_scheme_isi_process():
    assert route("What is the ISI mark certification process?") == "scheme_process"

def test_router_scheme_fmcs():
    assert route("Explain FMCS for foreign manufacturers") == "scheme_process"

# lab_query (3)
def test_router_lab_lrs():
    assert route("How does a lab get BIS recognition under LRS 2018?") == "lab_query"

def test_router_lab_recognition():
    assert route("What are the requirements for BIS laboratory recognition?") == "lab_query"

def test_router_lab_sample():
    assert route("Guidelines on handling of simplified samples for lab testing") == "lab_query"

# consumer_query (3) — P0
def test_router_consumer_verify_hallmark():
    assert route("How do I verify my jewelry has a genuine BIS hallmark?") == "consumer_query"

def test_router_consumer_huid():
    assert route("What does the HUID number on my jewelry mean?") == "consumer_query"

def test_router_consumer_fake_isi():
    assert route("I bought a product with a fake ISI mark, how do I report it?") == "consumer_query"
