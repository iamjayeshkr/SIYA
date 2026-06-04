"""
src/vani/reasoning/tools/mentor_mode.py
═══════════════════════════════════════════════════════════════════════════════
Langchain-compatible agent tools for Deep Document Mentor Mode.
Enables Vani to start mentor sessions, teach concepts, evaluate responses,
toggle Roast Mode, and view roadmap checkpoints.
"""

import logging
from langchain_core.tools import tool
import vani.services.mentor_service as mentor_service
import vani.memory.mentor_memory as mentor_db
import vani.memory.human_memory as human_memory

logger = logging.getLogger("vani.reasoning.tools.mentor_mode")


@tool
async def start_mentor_mode(roast_mode: str = "Off", mode_type: str = "document") -> str:
    """
    Shuru karta hai Deep Document Mentor Mode ya Repository Mentor Mode.
    - active document ko extract aur load karta hai roadmap ke liye
    - outline aur concept structure map instantly build karta hai
    - background indexing shuru karta hai coverage checks ke liye
    - Vani study buddy persona switch karti hai

    roast_mode: Roast intensity levels - "Off", "Light", "Medium", "Savage" (default "Off")
    mode_type: "document" for normal book/PDF/technical file, or "repository" for full codebase analysis

    Triggers: "start mentor mode", "Vani start study session", "mentor mode chalao",
              "learn document deeply", "study this book", "project architecture samjhao"
    """
    # 1. Fetch active document snapshot
    snapshot = human_memory.latest_temp_document_snapshot(max_chars=None)
    if not snapshot or not snapshot.get("id"):
        return (
            "❌ Koi active document nahi mila memory mein. "
            "Pehle book, PDF, document, ya code zip file upload karo, phir start karo!"
        )
        
    doc_id = snapshot["id"]
    filename = snapshot["filename"]
    full_text = snapshot["full_text"]
    
    # 2. Start session
    session = mentor_service.start_mentor_session(
        filename=filename,
        text=full_text,
        roast_mode=roast_mode,
        mode_type=mode_type,
    )
    
    status_msg = (
        f"🏆 **Deep Document Mentor Mode Active!** 🎓\n"
        f"📄 **Document**: {filename}\n"
        f"🔥 **Roast Level**: {roast_mode}\n"
        f"🛠️ **Mode**: {mode_type.capitalize()}\n\n"
        f"Main is document ka structure read kar chuki hoon. "
        f"First concept seekhne ke liye bolo: 'teach next concept'."
    )
    return status_msg


@tool
async def mentor_teach_next_concept() -> str:
    """
    Teaches the next unmastered concept from the roadmap.
    - auto-resolves prerequisite dependencies
    - generates beginner/intermediate/advanced dynamic explanations
    - pushes the visual Mermaid diagram to the UI sliding panel
    - starts the recall verification loop

    Triggers: "teach next concept", "explain next topic", "aage padhao", "next topic kya hai"
    """
    session = mentor_db.get_active_session()
    if not session:
        return "❌ Koi active study session nahi hai. Pehle mentor mode start karo!"
        
    doc_id = session["document_id"]
    next_cid = mentor_service.select_next_concept(doc_id)
    
    if not next_cid:
        # All mastered! Generate final report
        report = mentor_service.compile_final_mastery_report(doc_id)
        return (
            "🎉 **Congratulations! Saare concepts master ho gaye hain!** 🎓\n\n"
            + report
        )
        
    # Update active concept pointer
    mentor_db.update_session(doc_id, current_concept_id=next_cid)
    concept = mentor_service.get_concept_details(next_cid)
    concept_name = concept["name"] if concept else "Concept"
    
    # Adaptive teaching: choose strategy based on previous attempts
    attempts = concept.get("attempts", 0) if concept else 0
    strategy = mentor_service.TEACHING_STRATEGIES[attempts % len(mentor_service.TEACHING_STRATEGIES)]
    
    # Generate dynamic lesson narration & diagram
    narration, mermaid = mentor_service.generate_concept_explanation(
        concept_id=next_cid,
        strategy=strategy,
        level="Intermediate" if attempts > 0 else "Beginner",
    )
    
    # Push diagram to UI
    try:
        await send_teach_visual({
            "concept": concept_name,
            "visual_type": "diagram",
            "mermaid_code": mermaid,
            "narration": narration,
            "category": "humor" if session["roast_mode"] > 0 else "motivation",
            "subject": "general",
            "memory_context": [session["filename"]],
        })
    except Exception as e:
        logger.warning(f"Failed to push teach visual: {e}")
        
    # Generate active recall quiz item for this concept on-demand
    quiz = mentor_service.generate_mastery_quiz(next_cid)
    
    quiz_str = f"\n\n❓ **Mastery Quiz**:\n{quiz['question']}"
    if quiz.get("options"):
        for i, opt in enumerate(quiz["options"]):
            quiz_str += f"\n   {chr(65+i)}. {opt}"
            
    response = (
        f"📚 **Topic**: {concept_name} (Strategy: {strategy})\n\n"
        f"{narration}"
        f"{quiz_str}\n\n"
        f"Answer do, main check karti hoon! 🎯"
    )
    return response


@tool
async def mentor_quiz_answer(user_answer: str) -> str:
    """
    Submits user answer response for current concept quiz evaluation.
    - grades the response using the LLM
    - updates confidence score and concept mastery status
    - trigger strategy switches or chapter unlocks

    user_answer: text response or option letter (e.g. "A" or explanation)

    Triggers: "my answer is X", "correct answer is Y", "check my reply X"
    """
    session = mentor_db.get_active_session()
    if not session:
        return "❌ Koi active study session nahi hai."
        
    curr_cid = session["current_concept_id"]
    if not curr_cid:
        return "❌ Kisi concept pe quiz active nahi hai abhi."
        
    # Find active quiz item
    items = mentor_db.get_retention_items(curr_cid)
    if not items:
        return "❌ Is concept ka active quiz data nahi mila."
        
    # Get last unchecked or most recent quiz
    active_item = items[-1]
    
    passed, feedback, conf = mentor_service.evaluate_quiz_answer(
        active_item["id"],
        user_answer,
    )
    
    if passed:
        next_cid = mentor_service.select_next_concept(session["document_id"])
        next_btn = "\n\nBol 'teach next concept' aage badhne ke liye! 🚀" if next_cid else "\n\nAll concepts complete! Generate report."
        return (
            f"✅ **Check Passed!** (Mastery: {conf*100:.0f}%)\n\n"
            f"{feedback}"
            f"{next_btn}"
        )
    else:
        return (
            f"❌ **Review Needed** (Confidence: {conf*100:.0f}%)\n\n"
            f"{feedback}\n\n"
            f"Try again, or bol 'explain again' naye example ke liye!"
        )


@tool
async def mentor_status() -> str:
    """
    Returns current study progress indicators (coverage, mastery, active concept).

    Triggers: "mentor status", "progress check", "study score", "active roadmap"
    """
    session = mentor_db.get_active_session()
    if not session:
        return "Abhi koi active mentor study session nahi hai."
        
    curr_concept = "Intro"
    if session["current_concept_id"]:
        concept = mentor_service.get_concept_details(session["current_concept_id"])
        if concept:
            curr_concept = concept["name"]
            
    roast_lbl = {0: "Off", 1: "Light", 2: "Medium", 3: "Savage"}.get(session["roast_mode"], "Off")
    
    return (
        f"📊 **Study Dashboard**\n"
        f"📄 **Document**: {session['filename']}\n"
        f"📈 **Coverage progress**: {session['coverage_score']:.1f}%\n"
        f"🏆 **Mastery score**: {session['mastery_score']:.1f}%\n"
        f"📍 **Current Concept**: {curr_concept}\n"
        f"🔥 **Roast Level**: {roast_lbl}"
    )


@tool
async def mentor_toggle_roast(level: str) -> str:
    """
    Toggles the Roast Mode level between Off, Light, Medium, and Savage.

    level: Roast intensity setting - "Off", "Light", "Medium", "Savage"

    Triggers: "roast me", "change roast level to Savage", "roast toggle", "stop roasting"
    """
    session = mentor_db.get_active_session()
    if not session:
        return "❌ Koi active study session nahi hai."
        
    roast_int = {"Off": 0, "Light": 1, "Medium": 2, "Savage": 3}.get(level, 0)
    mentor_db.update_session(session["document_id"], roast_mode=roast_int)
    
    return f"🔥 Roast mode updated to **{level}**!"


@tool
async def mentor_final_report() -> str:
    """
    Compiles and returns the final markdown mastery review report.

    Triggers: "generate final study report", "mentor report", "roadmap compile"
    """
    session = mentor_db.get_active_session()
    if not session:
        return "❌ Active session nahi mila."
        
    report = mentor_service.compile_final_mastery_report(session["document_id"])
    return report
