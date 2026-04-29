from google.adk.agents import LlmAgent
from constants import AGENT_FALLBACK_MODELS, AGENT_NAME, AGENT_MODEL

from agent.fallback_gemini import FallbackGemini
from agent.student_prompt import FINAL_PROMPT
from agent.tools import (
    check_warranty,
    get_area_complaints,
    get_complaint_status,
    get_contractor_ledger,
    get_my_complaints,
    ping,
    submit_complaint,
    vote_on_complaint,
)

root_agent = LlmAgent(
    name=AGENT_NAME,
    model=FallbackGemini(
        model=AGENT_MODEL,
        fallback_models=AGENT_FALLBACK_MODELS,
    ),
    description="AWAAZ-PROOF civic contract audit agent",
    instruction=FINAL_PROMPT,
    tools=[
        ping,
        submit_complaint,
        get_complaint_status,
        vote_on_complaint,
        get_area_complaints,
        get_contractor_ledger,
        check_warranty,
        get_my_complaints,
    ],
)
