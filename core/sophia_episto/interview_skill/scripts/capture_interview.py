#!/usr/bin/env python3
"""
Interactive L2 Interview Capture Tool

Provides a structured CLI interface for conducting and recording L2 interviews.
Guides the interviewer through questions, captures responses, and extracts
frameworks, heuristics, and signals.

Usage:
    python capture_interview.py --respondent "Name" --domain rates
    python capture_interview.py --respondent "Name" --domain rates --section 1.1
    python capture_interview.py --resume session_abc123.json
"""

import json
import argparse
import uuid
from datetime import datetime
from pathlib import Path
import sys

# Question bank - loaded from questions.md structure
QUESTIONS = {
    "1.1": {
        "name": "Term Premium",
        "questions": [
            ("TP-1", "How do you decompose term premium? What are the component drivers you think about?"),
            ("TP-2", "Which of these drivers are slow-moving (regime-level) versus fast-moving (tactical)?"),
            ("TP-3", "When you say 'term premium is rich' or 'term premium is cheap,' what are you comparing it to? What's your reference point or fair value anchor?"),
            ("TP-4", "What's the relationship between term premium and duration supply? How do you think about that causality?"),
            ("TP-5", "Are there quantitative levels or thresholds that matter to you, or is it more about direction and momentum?"),
            ("TP-A1", "[ANECDOTE] Tell me about a time when your read on term premium was clearly right - you saw something others missed. What did you see and why did you trust it?"),
            ("TP-A2", "[ANECDOTE] Tell me about a time when term premium moved in a way that surprised you. What happened, and did it change how you think about it?"),
        ]
    },
    "1.2": {
        "name": "Positioning & Flows",
        "questions": [
            ("PF-1", "How do you think about positioning? What data or signals do you use to assess it?"),
            ("PF-2", "What's your mental model of who the main players are in rates markets and how they behave differently?"),
            ("PF-3", "When does positioning matter for price action versus when is it noise?"),
            ("PF-4", "How do you distinguish between 'crowded' and 'consensual but not crowded'?"),
            ("PF-5", "What flow dynamics do you watch? Are there predictable calendar effects or institutional patterns you rely on?"),
            ("PF-A1", "[ANECDOTE] Tell me about a time when you correctly identified that positioning was offsides before a move. What tipped you off?"),
            ("PF-A2", "[ANECDOTE] Tell me about a time when you underestimated how crowded a trade was. What did the unwind look like and what did you learn?"),
        ]
    },
    "1.3": {
        "name": "Fed Reaction Function",
        "questions": [
            ("FED-1", "How do you model what the Fed will do? What variables drive their decisions in your mental model?"),
            ("FED-2", "How do you weight what they say versus what they do? When does communication matter more than action?"),
            ("FED-3", "What's your framework for Fed credibility? How do you know when the market believes them versus doesn't?"),
            ("FED-4", "How do you think about the asymmetry in their reaction function - do they respond differently to upside versus downside surprises?"),
            ("FED-5", "How has your model of the Fed changed over time? What regime shifts have you lived through that updated your priors?"),
            ("FED-A1", "[ANECDOTE] Tell me about a time when you correctly anticipated a Fed pivot before consensus. What signaled the shift?"),
            ("FED-A2", "[ANECDOTE] Tell me about a time when Fed communication wrong-footed you. What did you miss in the messaging?"),
            ("FED-A3", "[ANECDOTE] Tell me about a time when the market's interpretation of a Fed event differed from yours. Who was right, and what did that teach you?"),
        ]
    },
    "1.4": {
        "name": "Supply Dynamics",
        "questions": [
            ("SUP-1", "How do you think about Treasury supply? What's your framework for when supply matters versus when it's absorbed without impact?"),
            ("SUP-2", "What's the relationship between supply, term premium, and auction outcomes in your mental model?"),
            ("SUP-3", "How do you think about the demand side - who are the marginal buyers at different points in the cycle?"),
            ("SUP-4", "What supply-related signals have predictive value for you?"),
            ("SUP-A1", "[ANECDOTE] Tell me about a time when supply dynamics drove a move that the macro narrative missed. What happened?"),
            ("SUP-A2", "[ANECDOTE] Tell me about a time when you expected supply to matter and it didn't. What absorbed it?"),
        ]
    },
    "1.5": {
        "name": "Macro Regime",
        "questions": [
            ("REG-1", "How do you define the current macro regime? What are the key state variables?"),
            ("REG-2", "What tells you a regime is shifting versus experiencing noise within a stable regime?"),
            ("REG-3", "How do you think about the interaction between growth, inflation, and policy? Is there a hierarchy?"),
            ("REG-4", "What's your framework for fiscal-monetary interaction? When do fiscal dynamics dominate?"),
            ("REG-A1", "[ANECDOTE] Tell me about a time when you correctly identified a regime shift early. What were the early signals?"),
            ("REG-A2", "[ANECDOTE] Tell me about a time when you thought the regime was shifting but it was just noise. What fooled you?"),
        ]
    },
    "2.1": {
        "name": "Conviction Formation",
        "questions": [
            ("CF-1", "What combination of signals gives you high conviction? Is there a pattern?"),
            ("CF-2", "What makes you override your base case? What type of new information changes your mind?"),
            ("CF-3", "How do you distinguish between 'I'm early' and 'I'm wrong'?"),
            ("CF-4", "What's your process when multiple frameworks point in different directions?"),
            ("CF-A1", "[ANECDOTE] Tell me about a time when you had unusually high conviction and it paid off. What gave you that confidence?"),
            ("CF-A2", "[ANECDOTE] Tell me about a time when you had high conviction and it was wrong. What was the error - the analysis or the expression?"),
            ("CF-A3", "[ANECDOTE] Tell me about a time when you correctly changed your mind mid-trade. What triggered the update?"),
        ]
    },
    "2.2": {
        "name": "Trade Expression",
        "questions": [
            ("TE-1", "How do you choose between outright duration, curve, and RV expressions?"),
            ("TE-2", "What makes a trade 'clean' versus 'messy' in your mind?"),
            ("TE-3", "When do you prefer optionality versus delta? What drives that choice?"),
            ("TE-4", "How do you think about carry versus roll versus capital appreciation?"),
            ("TE-A1", "[ANECDOTE] Tell me about a time when you had the right view but the wrong expression. What would have been better?"),
            ("TE-A2", "[ANECDOTE] Tell me about a time when the expression saved you despite an imperfect view. What made it resilient?"),
        ]
    },
    "2.3": {
        "name": "Risk & Sizing",
        "questions": [
            ("RS-1", "How do you size positions relative to conviction? Is there a rough mapping?"),
            ("RS-2", "What makes you cut a position before your thesis is invalidated?"),
            ("RS-3", "How do you think about correlated risks across positions?"),
            ("RS-4", "What's your mental model of liquidity - when does it matter and when can you ignore it?"),
            ("RS-A1", "[ANECDOTE] Tell me about a time when you sized correctly for uncertainty - stayed small enough to survive being wrong. What made you hold back?"),
            ("RS-A2", "[ANECDOTE] Tell me about a time when you wished you'd sized bigger. What stopped you?"),
            ("RS-A3", "[ANECDOTE] Tell me about a time when liquidity mattered more than you expected. What happened?"),
        ]
    },
    "3.1": {
        "name": "Historical Misses",
        "questions": [
            ("HM-1", "What's a trade or view that was wrong in a way that taught you something durable?"),
            ("HM-2", "What framework failed, and how did you update it?"),
            ("HM-3", "Are there market conditions where your usual approach doesn't work? What are the signatures of those conditions?"),
            ("HM-A1", "[ANECDOTE] Tell me about your most painful loss that wasn't due to bad luck. What was the actual mistake?"),
            ("HM-A2", "[ANECDOTE] Tell me about a time you were right for the wrong reasons. Did you realize it at the time?"),
        ]
    },
    "3.2": {
        "name": "Known Limitations",
        "questions": [
            ("KL-1", "What aspects of rates markets do you feel you understand well versus poorly?"),
            ("KL-2", "What types of moves consistently surprise you?"),
            ("KL-3", "Where do you know you have blind spots?"),
        ]
    },
    "3.3": {
        "name": "Epistemic Pitfalls",
        "questions": [
            ("EP-1", "When do you tend to hold a view too long? What's the pattern?"),
            ("EP-2", "When do you tend to give up too early?"),
            ("EP-3", "What emotional or cognitive states lead to your worst decisions?"),
            ("EP-A1", "[ANECDOTE] Tell me about a time when you knew you were in a bad mental state for trading but traded anyway. What happened?"),
            ("EP-A2", "[ANECDOTE] Tell me about a time when you caught yourself rationalizing a position. What snapped you out of it?"),
        ]
    },
    "4.1": {
        "name": "Regime Dependence",
        "questions": [
            ("RD-1", "Which of your frameworks are regime-dependent? What defines the applicable regime?"),
            ("RD-2", "How do you know when you've shifted into a regime where your playbook doesn't apply?"),
            ("RD-3", "What's an example of a framework that worked in one regime and failed in another?"),
            ("RD-A1", "[ANECDOTE] Tell me about the hardest regime transition you've traded through. What made it hard and how did you adapt?"),
        ]
    },
    "4.2": {
        "name": "Cross-Market Interactions",
        "questions": [
            ("CM-1", "When do cross-market signals (equities, credit, FX, commodities) matter for rates?"),
            ("CM-2", "How do you think about correlation regime shifts?"),
            ("CM-3", "What cross-market dynamics do you watch as leading indicators?"),
            ("CM-A1", "[ANECDOTE] Tell me about a time when a cross-market signal gave you edge in rates. What was the connection?"),
            ("CM-A2", "[ANECDOTE] Tell me about a time when correlations broke down on you. What was the shock?"),
        ]
    },
    "4.3": {
        "name": "Scope Limits",
        "questions": [
            ("SL-1", "What parts of the rates market do you explicitly avoid or feel underqualified to trade?"),
            ("SL-2", "What types of analysis do you rely on others for?"),
            ("SL-3", "Where does your edge end?"),
        ]
    },
    "5.1": {
        "name": "Information Processing",
        "questions": [
            ("IP-1", "What sources do you trust most? Why?"),
            ("IP-2", "How do you distinguish signal from noise in research?"),
            ("IP-3", "What makes you update a view based on research versus dismiss it as noise?"),
            ("IP-A1", "[ANECDOTE] Tell me about a time when a piece of research genuinely changed your view. What made it credible?"),
            ("IP-A2", "[ANECDOTE] Tell me about a time when you initially dismissed something that turned out to be important. What did you learn about your filters?"),
        ]
    },
    "5.2": {
        "name": "Market Epistemics",
        "questions": [
            ("ME-1", "When is consensus informative versus when is it something to fade?"),
            ("ME-2", "How do you think about what's priced in versus what isn't?"),
            ("ME-3", "What's your model of how information gets incorporated into rates markets?"),
            ("ME-A1", "[ANECDOTE] Tell me about a time when you correctly faded consensus. What told you the crowd was wrong?"),
            ("ME-A2", "[ANECDOTE] Tell me about a time when you faded consensus and got run over. What did consensus know that you didn't?"),
        ]
    },
    "5.3": {
        "name": "Self-Calibration",
        "questions": [
            ("SC-1", "How do you know when you're calibrated versus overconfident or underconfident?"),
            ("SC-2", "What feedback loops do you use to assess your own accuracy?"),
            ("SC-3", "How do you distinguish skill from luck in your own performance?"),
            ("SC-A1", "[ANECDOTE] Tell me about a period when you were running hot. How did you know whether it was skill or conditions?"),
            ("SC-A2", "[ANECDOTE] Tell me about a period when nothing worked. How did you diagnose whether it was you or the market?"),
        ]
    },
}


def clear_screen():
    """Clear terminal screen."""
    print("\033[2J\033[H", end="")


def print_header(text: str):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_subheader(text: str):
    """Print a formatted subheader."""
    print("\n" + "-" * 50)
    print(f"  {text}")
    print("-" * 50 + "\n")


def get_input(prompt: str, allow_empty: bool = False) -> str:
    """Get input from user with optional empty validation."""
    while True:
        response = input(prompt).strip()
        if response or allow_empty:
            return response
        print("  [Response required. Enter 'skip' to skip this question.]")


def get_multiline_input(prompt: str) -> str:
    """Get multi-line input, ending with empty line."""
    print(prompt)
    print("  (Enter response, then press Enter twice to finish, or 'skip' to skip)")
    print()
    
    lines = []
    while True:
        line = input()
        if line.lower() == 'skip':
            return 'SKIPPED'
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    
    return "\n".join(lines).strip()


def get_choice(prompt: str, options: list) -> str:
    """Get a choice from a list of options."""
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    
    while True:
        choice = input("\nEnter number: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print("  Invalid choice. Please enter a number.")


def extract_from_response(response: str, question_id: str) -> dict:
    """Interactive extraction of frameworks, heuristics, signals from response."""
    
    if response == 'SKIPPED':
        return {
            "frameworks": [],
            "heuristics": [],
            "signals": [],
            "boundaries": []
        }
    
    print_subheader("Extraction")
    print("Let's extract structured knowledge from this response.\n")
    
    extracted = {
        "frameworks": [],
        "heuristics": [],
        "signals": [],
        "boundaries": []
    }
    
    # Frameworks
    print("FRAMEWORKS (decompositions, mental models, causal relationships)")
    while True:
        add = input("  Add a framework? (y/n): ").strip().lower()
        if add != 'y':
            break
        
        fw = {
            "name": get_input("    Framework name: "),
            "components": [],
            "relationships": []
        }
        
        print("    Components (enter each, empty line when done):")
        while True:
            comp = input("      - ").strip()
            if not comp:
                break
            fw["components"].append(comp)
        
        print("    Relationships (enter each, empty line when done):")
        while True:
            rel = input("      - ").strip()
            if not rel:
                break
            fw["relationships"].append(rel)
        
        extracted["frameworks"].append(fw)
    
    # Heuristics
    print("\nHEURISTICS (if/then rules, decision triggers)")
    while True:
        add = input("  Add a heuristic? (y/n): ").strip().lower()
        if add != 'y':
            break
        
        h = {
            "condition": get_input("    When/If: "),
            "action": get_input("    Then: "),
            "confidence": get_choice("    Confidence:", ["high", "medium", "low"])
        }
        extracted["heuristics"].append(h)
    
    # Signals
    print("\nSIGNALS (data points, indicators they watch)")
    while True:
        add = input("  Add a signal? (y/n): ").strip().lower()
        if add != 'y':
            break
        
        s = {
            "signal": get_input("    Signal: "),
            "interpretation": get_input("    Interpretation: "),
            "leading_indicator": input("    Leading indicator? (y/n): ").strip().lower() == 'y'
        }
        extracted["signals"].append(s)
    
    # Boundaries
    print("\nBOUNDARIES (limitations, when frameworks break)")
    while True:
        add = input("  Add a boundary? (y/n): ").strip().lower()
        if add != 'y':
            break
        
        b = {
            "framework": get_input("    Which framework: "),
            "limitation": get_input("    Limitation: "),
            "regime": get_input("    Applicable regime: ")
        }
        extracted["boundaries"].append(b)
    
    return extracted


def infer_confidence(response: str) -> tuple:
    """Help interviewer assess confidence level."""
    print("\nCONFIDENCE ASSESSMENT")
    print("Based on the response, what confidence level would you infer?")
    print("  Indicators of HIGH: definitive language, quick answers, specific examples")
    print("  Indicators of MEDIUM: qualified language, 'usually', 'generally'")
    print("  Indicators of LOW: hedging, 'I think', long pauses, contradictions")
    
    inferred = get_choice("\nInferred confidence:", ["high", "medium", "low"])
    reasoning = get_input("Brief reasoning: ", allow_empty=True)
    
    return inferred, reasoning


def capture_response(question_id: str, question_text: str, respondent: dict, 
                     session_id: str, domain: str) -> dict:
    """Capture a single response with extraction."""
    
    print_subheader(f"Question {question_id}")
    print(f"{question_text}\n")
    
    raw_response = get_multiline_input("RESPONSE:")
    
    if raw_response == 'SKIPPED':
        return {
            "response_id": str(uuid.uuid4()),
            "question_id": question_id,
            "question_text": question_text,
            "respondent": respondent,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "raw_response": "SKIPPED",
            "extracted": {"frameworks": [], "heuristics": [], "signals": [], "boundaries": []},
            "confidence": {"stated": None, "inferred": None, "reasoning": "Skipped"},
            "follow_ups_needed": [],
            "anecdote_present": False,
            "anecdote_summary": None,
            "tags": [],
            "domain": domain
        }
    
    # Extract structured knowledge
    extracted = extract_from_response(raw_response, question_id)
    
    # Confidence
    inferred_conf, conf_reasoning = infer_confidence(raw_response)
    
    # Follow-ups
    print("\nFOLLOW-UPS NEEDED")
    follow_ups = []
    while True:
        add = input("  Add a follow-up question? (y/n): ").strip().lower()
        if add != 'y':
            break
        follow_ups.append({
            "question": get_input("    Question: "),
            "reason": get_input("    Reason: ")
        })
    
    # Anecdote check
    is_anecdote = "[ANECDOTE]" in question_text or question_id.endswith(('A1', 'A2', 'A3'))
    anecdote_summary = None
    if is_anecdote and raw_response != 'SKIPPED':
        anecdote_summary = get_input("\nBrief anecdote summary (1 sentence): ", allow_empty=True)
    
    # Tags
    print("\nTAGS (enter comma-separated, e.g., term_premium, supply, auctions):")
    tags_input = get_input("  Tags: ", allow_empty=True)
    tags = [t.strip() for t in tags_input.split(",")] if tags_input else []
    
    return {
        "response_id": str(uuid.uuid4()),
        "question_id": question_id,
        "question_text": question_text,
        "respondent": respondent,
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "raw_response": raw_response,
        "extracted": extracted,
        "confidence": {
            "stated": None,
            "inferred": inferred_conf,
            "reasoning": conf_reasoning
        },
        "follow_ups_needed": follow_ups,
        "anecdote_present": is_anecdote and raw_response != 'SKIPPED',
        "anecdote_summary": anecdote_summary,
        "tags": tags,
        "domain": domain
    }


def save_session(session: dict, filepath: Path):
    """Save session to JSON file."""
    with open(filepath, 'w') as f:
        json.dump(session, f, indent=2)
    print(f"\n  [Session saved to {filepath}]")


def load_session(filepath: Path) -> dict:
    """Load session from JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def run_interview(respondent_name: str, domain: str, trust_level: str, 
                  sections: list = None, resume_session: dict = None):
    """Run the interactive interview."""
    
    # Initialize or resume session
    if resume_session:
        session = resume_session
        session_id = session['session_id']
        respondent = session['respondent']
        completed_questions = {r['question_id'] for r in session['responses']}
        print(f"\n  Resuming session {session_id}")
        print(f"  {len(completed_questions)} questions already completed\n")
    else:
        session_id = str(uuid.uuid4())[:8]
        respondent = {
            "name": respondent_name,
            "domain_expertise": [domain],
            "trust_level": trust_level
        }
        session = {
            "session_id": session_id,
            "respondent": respondent,
            "session_date": datetime.now().isoformat(),
            "sections_covered": [],
            "duration_minutes": 0,
            "responses": [],
            "session_notes": "",
            "gaps_identified": []
        }
        completed_questions = set()
    
    session_file = Path(f"session_{session_id}.json")
    
    # Determine sections to cover
    if sections:
        sections_to_cover = [s for s in sections if s in QUESTIONS]
    else:
        sections_to_cover = list(QUESTIONS.keys())
    
    print_header(f"L2 Interview: {respondent_name}")
    print(f"  Domain: {domain}")
    print(f"  Trust level: {trust_level}")
    print(f"  Session ID: {session_id}")
    print(f"  Sections: {', '.join(sections_to_cover)}")
    print("\n  Commands during interview:")
    print("    'skip' - Skip current question")
    print("    'pause' - Save and exit (can resume later)")
    print("    'notes' - Add session notes")
    
    input("\n  Press Enter to begin...")
    
    start_time = datetime.now()
    
    try:
        for section_id in sections_to_cover:
            section = QUESTIONS[section_id]
            print_header(f"Section {section_id}: {section['name']}")
            
            for q_id, q_text in section['questions']:
                if q_id in completed_questions:
                    print(f"  [Skipping {q_id} - already completed]")
                    continue
                
                response = capture_response(
                    q_id, q_text, respondent, session_id, domain
                )
                session['responses'].append(response)
                completed_questions.add(q_id)
                
                # Auto-save after each response
                save_session(session, session_file)
                
                # Check for pause command
                cont = input("\n  Continue? (Enter/pause/notes): ").strip().lower()
                if cont == 'pause':
                    raise KeyboardInterrupt
                elif cont == 'notes':
                    note = get_input("  Session note: ")
                    session['session_notes'] += f"\n[{datetime.now().isoformat()}] {note}"
            
            if section_id not in session['sections_covered']:
                session['sections_covered'].append(section_id)
    
    except KeyboardInterrupt:
        print("\n\n  [Interview paused]")
    
    # Calculate duration
    end_time = datetime.now()
    session['duration_minutes'] = int((end_time - start_time).total_seconds() / 60)
    
    # Final save
    save_session(session, session_file)
    
    # Summary
    print_header("Session Summary")
    print(f"  Responses captured: {len(session['responses'])}")
    print(f"  Sections covered: {', '.join(session['sections_covered'])}")
    print(f"  Duration: {session['duration_minutes']} minutes")
    print(f"  Session file: {session_file}")
    
    # Identify gaps
    print("\n  Identifying gaps...")
    for section_id in sections_to_cover:
        section = QUESTIONS[section_id]
        section_questions = {q[0] for q in section['questions']}
        answered = section_questions & completed_questions
        if len(answered) < len(section_questions):
            gap = {
                "section": section_id,
                "gap": f"{len(section_questions) - len(answered)} questions unanswered",
                "priority": "medium"
            }
            session['gaps_identified'].append(gap)
            print(f"    Section {section_id}: {gap['gap']}")
    
    save_session(session, session_file)
    
    print(f"\n  To resume: python capture_interview.py --resume {session_file}")
    print(f"  To generate L2: python generate_l2.py {session_file} -o {domain}_l2.yaml")


def main():
    parser = argparse.ArgumentParser(
        description='Interactive L2 Interview Capture Tool'
    )
    parser.add_argument('--respondent', '-r', help='Respondent name')
    parser.add_argument('--domain', '-d', default='rates',
                        help='Primary domain (default: rates)')
    parser.add_argument('--trust', '-t', default='expert',
                        choices=['expert', 'knowledgeable', 'learning'],
                        help='Trust level (default: expert)')
    parser.add_argument('--section', '-s', action='append',
                        help='Specific section(s) to cover (can repeat)')
    parser.add_argument('--resume', help='Resume from session file')
    parser.add_argument('--list-sections', action='store_true',
                        help='List available sections and exit')
    
    args = parser.parse_args()
    
    if args.list_sections:
        print("\nAvailable sections:")
        for section_id, section in QUESTIONS.items():
            print(f"  {section_id}: {section['name']} ({len(section['questions'])} questions)")
        return
    
    if args.resume:
        session = load_session(Path(args.resume))
        run_interview(
            session['respondent']['name'],
            session['respondent']['domain_expertise'][0],
            session['respondent']['trust_level'],
            sections=args.section,
            resume_session=session
        )
    elif args.respondent:
        run_interview(
            args.respondent,
            args.domain,
            args.trust,
            sections=args.section
        )
    else:
        parser.print_help()
        print("\n  Example: python capture_interview.py -r 'John Smith' -d rates")


if __name__ == '__main__':
    main()
