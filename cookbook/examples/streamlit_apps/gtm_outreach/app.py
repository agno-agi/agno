import os

import streamlit as st
from agent import (
    create_company_finder_agent,
    create_contact_finder_agent,
    create_email_writer_agent,
    create_phone_finder_agent,
    create_research_agent,
    run_company_finder,
    run_contact_finder,
    run_email_writer,
    run_phone_finder,
    run_research,
)


def main() -> None:
    st.set_page_config(page_title="GTM B2B Outreach", layout="wide")

    # Sidebar: API keys
    st.sidebar.header("API Configuration")
    openai_key = st.sidebar.text_input(
        "OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", "")
    )
    exa_key = st.sidebar.text_input(
        "Exa API Key", type="password", value=os.getenv("EXA_API_KEY", "")
    )
    if openai_key:
        os.environ["OPENAI_API_KEY"] = openai_key
    if exa_key:
        os.environ["EXA_API_KEY"] = exa_key

    if not openai_key or not exa_key:
        st.sidebar.warning("Enter both API keys to enable the app")

    # Inputs
    st.title("GTM B2B Outreach Multi Agent Team")
    col1, col2 = st.columns(2)
    with col1:
        target_desc = st.text_area("Target companies", height=100)
        offering_desc = st.text_area("Your offering", height=100)
    with col2:
        sender_name = st.text_input("Your name", value="Sales Team")
        sender_company = st.text_input("Your company", value="Our Company")
        calendar_link = st.text_input("Calendar link (optional)", value="")
        num_companies = st.number_input(
            "Number of companies", min_value=1, max_value=10, value=5
        )
        email_style = st.selectbox(
            "Email style", ["Professional", "Casual", "Cold", "Consultative"]
        )

    if st.button("Start Outreach", type="primary"):
        if not openai_key or not exa_key:
            st.error("Please provide API keys")
        elif not target_desc or not offering_desc:
            st.error("Please fill in target companies and offering")
        else:
            progress = st.progress(0)
            stage_msg = st.empty()
            details = st.empty()
            try:
                company_agent = create_company_finder_agent()
                contact_agent = create_contact_finder_agent()
                phone_agent = create_phone_finder_agent()
                research_agent = create_research_agent()
                email_agent = create_email_writer_agent(email_style)

                # Run pipeline
                stage_msg.info("1/5 Finding companies...")
                companies = run_company_finder(
                    company_agent,
                    target_desc.strip(),
                    offering_desc.strip(),
                    int(num_companies),
                )
                progress.progress(20)

                stage_msg.info("2/5 Finding contacts...")
                contacts_data = run_contact_finder(
                    contact_agent, companies, target_desc, offering_desc
                )
                progress.progress(40)

                stage_msg.info("3/5 Finding phones...")
                phone_data = run_phone_finder(phone_agent, contacts_data)
                progress.progress(60)

                stage_msg.info("4/5 Researching insights...")
                research_data = run_research(research_agent, companies)
                progress.progress(80)

                stage_msg.info("5/5 Writing emails...")
                emails = run_email_writer(
                    email_agent,
                    contacts_data,
                    research_data,
                    offering_desc,
                    sender_name,
                    sender_company,
                    calendar_link,
                )
                progress.progress(100)

                st.session_state["gtm_results"] = {
                    "companies": companies,
                    "contacts": contacts_data,
                    "phones": phone_data,
                    "research": research_data,
                    "emails": emails,
                }
                stage_msg.success("Completed")
            except Exception as e:
                stage_msg.error("Pipeline failed")
                st.error(str(e))

    # Results
    results = st.session_state.get("gtm_results")
    if results:
        st.subheader("Top Companies")
        for idx, c in enumerate(results["companies"], 1):
            st.markdown(f"**{idx}. {c.get('name', '')}**")
            st.write(c.get("website", ""))
            st.write(c.get("why_fit", ""))

        st.subheader("Contacts")
        for c in results["contacts"]:
            st.markdown(f"**{c.get('name', '')}**")
            for p in c.get("contacts", []):
                inferred = " (inferred)" if p.get("inferred") else ""
                st.write(
                    f"- {p.get('full_name', '')} | {p.get('title', '')} | {p.get('email', '')}{inferred}"
                )

        st.subheader("Phones")
        for c in results["phones"]:
            st.markdown(f"**{c.get('name', '')}**")
            for p in c.get("contacts", []):
                st.write(
                    f"- {p.get('full_name', '')} | {p.get('phone_number', '')} ({p.get('phone_type', '')}) {'✓' if p.get('verified') else '~'}"
                )

        st.subheader("Research Insights")
        for r in results["research"]:
            st.markdown(f"**{r.get('name', '')}**")
            for ins in r.get("insights", []):
                st.write(f"- {ins}")

        st.subheader("Emails")
        for i, e in enumerate(results["emails"], 1):
            with st.expander(f"{i}. {e.get('company', '')} → {e.get('contact', '')}"):
                st.write(f"Subject: {e.get('subject', '')}")
                st.text(e.get("body", ""))


if __name__ == "__main__":
    main()
