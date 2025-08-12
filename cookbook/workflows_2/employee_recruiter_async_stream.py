import asyncio
import io
import random
from datetime import datetime, timedelta
from typing import Any, List

import requests
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.workflow.v2.types import WorkflowExecutionInput
from agno.workflow.v2.workflow import Workflow
from pydantic import BaseModel, Field
from pypdf import PdfReader


# --- Response models ---
class ScreeningResult(BaseModel):
    name: str
    email: str
    score: float
    feedback: str


class ScheduledCall(BaseModel):
    name: str
    email: str
    call_time: str
    url: str


class EmailContent(BaseModel):
    subject: str
    body: str


# --- PDF utility ---
def extract_text_from_pdf(url: str) -> str:
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        print(f"Error extracting PDF from {url}: {e}")
        return ""


# --- Simulation tools ---
def simulate_zoom_scheduling(
    agent: Agent, candidate_name: str, candidate_email: str
) -> str:
    """Simulate Zoom call scheduling"""
    # Generate a future time slot (1-7 days from now, between 10am-6pm IST)
    base_time = datetime.now() + timedelta(days=random.randint(1, 7))
    hour = random.randint(10, 17)  # 10am to 5pm
    scheduled_time = base_time.replace(hour=hour, minute=0, second=0, microsecond=0)

    # Generate fake Zoom URL
    meeting_id = random.randint(100000000, 999999999)
    zoom_url = f"https://zoom.us/j/{meeting_id}"

    result = f"✅ Zoom call scheduled successfully!\n"
    result += f"📅 Time: {scheduled_time.strftime('%Y-%m-%d %H:%M')} IST\n"
    result += f"🔗 Meeting URL: {zoom_url}\n"
    result += f"👤 Participant: {candidate_name} ({candidate_email})"

    return result


def simulate_email_sending(agent: Agent, to_email: str, subject: str, body: str) -> str:
    """Simulate email sending"""
    result = f"📧 Email sent successfully!\n"
    result += f"📮 To: {to_email}\n"
    result += f"📝 Subject: {subject}\n"
    result += f"✉️ Body length: {len(body)} characters\n"
    result += f"🕐 Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    return result


# --- Agents ---
screening_agent = Agent(
    name="Screening Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Screen candidate given resume text and job description.",
        "Provide a score from 0-10 based on how well they match the job requirements.",
        "Give specific feedback on strengths and areas of concern.",
        "Extract the candidate's name and email from the resume if available.",
    ],
    response_model=ScreeningResult,
)

scheduler_agent = Agent(
    name="Scheduler Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        f"You are scheduling interview calls. Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST",
        "Schedule calls between 10am-6pm IST on weekdays.",
        "Use the simulate_zoom_scheduling tool to create the meeting.",
        "Provide realistic future dates and times.",
    ],
    tools=[simulate_zoom_scheduling],
    response_model=ScheduledCall,
)

email_writer_agent = Agent(
    name="Email Writer Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Write professional, friendly interview invitation emails.",
        "Include congratulations, interview details, and next steps.",
        "Keep emails concise but warm and welcoming.",
        "Sign emails as 'John Doe, Senior Software Engineer' with email john@agno.com",
    ],
    response_model=EmailContent,
)

email_sender_agent = Agent(
    name="Email Sender Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You send emails using the simulate_email_sending tool.",
        "Always confirm successful delivery with details.",
    ],
    tools=[simulate_email_sending],
)


# --- Execution function ---
async def recruitment_execution(
    workflow: Workflow,
    execution_input: WorkflowExecutionInput,
    job_description: str,
    **kwargs: Any,
):
    """Execute the complete recruitment workflow"""

    # Get inputs
    message: str = execution_input.message
    jd: str = job_description
    resumes: List[str] = kwargs.get("candidate_resume_urls", [])

    if not resumes:
        yield "❌ No candidate resume URLs provided"

    if not jd:
        yield "❌ No job description provided"

    print(f"🚀 Starting recruitment process for {len(resumes)} candidates")
    print(f"📋 Job Description: {jd[:100]}{'...' if len(jd) > 100 else ''}")

    selected_candidates: List[ScreeningResult] = []

    # Phase 1: Screening
    print(f"\n📊 PHASE 1: CANDIDATE SCREENING")
    print("=" * 50)

    for i, url in enumerate(resumes, 1):
        print(f"\n🔍 Processing candidate {i}/{len(resumes)}")

        # Extract resume text (with caching)
        if url not in workflow.workflow_session_state:
            print(f"📄 Extracting text from: {url}")
            workflow.workflow_session_state[url] = extract_text_from_pdf(url)
        else:
            print(f"📋 Using cached resume content")

        resume_text = workflow.workflow_session_state[url]

        if not resume_text:
            print(f"❌ Could not extract text from resume")
            continue

        # Screen the candidate
        screening_prompt = f"""
        {message}
        Please screen this candidate for the job position.

        RESUME:
        {resume_text}

        JOB DESCRIPTION:
        {jd}

        Evaluate how well this candidate matches the job requirements and provide a score from 0-10.
        """

        async for response in await screening_agent.arun(
            screening_prompt, stream=True, stream_intermediate_steps=True
        ):
            if hasattr(response, "content") and response.content:
                candidate = response.content

        print(f"👤 Candidate: {candidate.name}")
        print(f"📧 Email: {candidate.email}")
        print(f"⭐ Score: {candidate.score}/10")
        print(
            f"💭 Feedback: {candidate.feedback[:150]}{'...' if len(candidate.feedback) > 150 else ''}"
        )

        if candidate.score >= 5.0:
            selected_candidates.append(candidate)
            print(f"✅ SELECTED for interview!")
        else:
            print(f"❌ Not selected (score below 5.0)")

    # Phase 2: Interview Scheduling & Email Communication
    if selected_candidates:
        print(f"\n📅 PHASE 2: INTERVIEW SCHEDULING")
        print("=" * 50)

        for i, candidate in enumerate(selected_candidates, 1):
            print(
                f"\n🗓️ Scheduling interview {i}/{len(selected_candidates)} for {candidate.name}"
            )

            # Schedule interview
            schedule_prompt = f"""
            Schedule a 1-hour interview call for:
            - Candidate: {candidate.name}
            - Email: {candidate.email}
            - Interviewer: Dirk Brand (dirk@phidata.com)

            Use the simulate_zoom_scheduling tool to create the meeting.
            """

            async for response in await scheduler_agent.arun(
                schedule_prompt, stream=True, stream_intermediate_steps=True
            ):
                if hasattr(response, "content") and response.content:
                    scheduled_call = response.content

            print(f"📅 Scheduled for: {scheduled_call.call_time}")
            print(f"🔗 Meeting URL: {scheduled_call.url}")

            # Write congratulatory email
            email_prompt = f"""
            Write a professional interview invitation email for:
            - Candidate: {candidate.name} ({candidate.email})
            - Interview time: {scheduled_call.call_time}
            - Meeting URL: {scheduled_call.url}
            - Congratulate them on being selected
            - Include next steps and what to expect
            """

            async for response in await email_writer_agent.arun(
                email_prompt, stream=True, stream_intermediate_steps=True
            ):
                if hasattr(response, "content") and response.content:
                    email_content = response.content

            print(f"✏️ Email subject: {email_content.subject}")

            # Send email
            send_prompt = f"""
            Send the interview invitation email:
            - To: {candidate.email}
            - Subject: {email_content.subject}
            - Body: {email_content.body}

            Use the simulate_email_sending tool.
            """

            async for response in await email_sender_agent.arun(
                send_prompt, stream=True, stream_intermediate_steps=True
            ):
                yield response


# --- Workflow definition ---
recruitment_workflow = Workflow(
    name="Employee Recruitment Workflow (Simulated)",
    description="Automated candidate screening with simulated scheduling and email",
    storage=SqliteStorage(
        table_name="recruiter_workflow_sessions",
        db_file="tmp/workflows.db",
        mode="workflow_v2",
    ),
    steps=recruitment_execution,
    workflow_session_state={},
)


if __name__ == "__main__":
    # Test with sample data
    print("🧪 Testing Employee Recruitment Workflow with Simulated Tools")
    print("=" * 60)

    asyncio.run(
        recruitment_workflow.aprint_response(
            message="Process candidates for backend engineer position",
            candidate_resume_urls=[
                "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/cv_1.pdf",
                "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/cv_2.pdf",
            ],
            job_description="""
        We are hiring for backend and systems engineers!
        Join our team building the future of agentic software

        Requirements:
        🧠 You know your way around Python, typescript, docker, and AWS.
        ⚙️ Love to build in public and contribute to open source.
        🚀 Are ok dealing with the pressure of an early-stage startup.
        🏆 Want to be a part of the biggest technological shift since the internet.
        🌟 Bonus: experience with infrastructure as code.
        🌟 Bonus: starred Agno repo.
        """,
            stream=True,
            stream_intermediate_steps=True,
        )
    )
