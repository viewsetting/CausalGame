from .base import Colors, BaseHandler
from typing import Dict, Any

def generate_mission_report(client: Any, drones_used: int, total_drones: int, hp_used: int) -> str:
    """Generates and prints the final mission report."""
    print(f"\n{Colors.BOLD}{Colors.GREEN}=== MISSION COMPLETE ==={Colors.RESET}")
    final_report = "MISSION REPORT:\n"
    
    try:
        final_status = client.get_status()
        final_eval = final_status.get('final_evaluation')
        
        if final_eval:
            # Display Stage 2 Metrics
            s_rate = final_eval['survival_rate']
            s_count = final_eval['survived']
            expense = final_eval['cost_used']
            
            print(f"{Colors.YELLOW}>> OFFICIAL STAGE 2 RESULT <<{Colors.RESET}")
            print(f"Survival Rate: {Colors.BOLD}{s_rate}{Colors.RESET}")
            print(f"Survivors: {s_count}/50")
            print(f"Cost Used: {expense}")
            print(f"Stage 1 Exploration: {drones_used} Drones Used")
            
            final_report += f"OFFICIAL RESULT (Stage 2): {s_rate} Survival ({s_count}/50)\n"
            final_report += f"Design Cost: {expense}\n"
            final_report += f"Exploration Efficiency: {drones_used} drones used to find solution.\n"
            
        else:
            # Fallback to Stage 1 Stats (If agent failed to submit)
            print(f"{Colors.RED}WARNING: No Final Design Submitted.{Colors.RESET}")
            print(f"Total Drones Deployed: {drones_used}/{total_drones}")
            print(f"Total HP Budget Used: {hp_used}")
            
            final_report += "RESULT: FAILED (No Final Design Submitted)\n"
            final_report += f"Stage 1 Stats: {drones_used}/{total_drones} deployed.\n"
            
            # Calculate Stage 1 Rate for context
            data = client.get_mission_data()
            session_drones = [d for d in data if str(d['id']).startswith('SESSION')]
            session_survivors = [d for d in session_drones if d['status'] == 'RETURNED']
            if drones_used > 0:
                rate = (len(session_survivors) / drones_used) * 100
                print(f"Exploration Survival Rate: {rate:.1f}%")
                final_report += f"Exploration Survival Rate: {rate:.1f}%\n"

    except Exception as e:
        print(f"Error generating report: {e}")
        final_report += "Error retrieving final status.\n"
        
    return final_report

def request_final_reflection(agent: BaseHandler, final_report: str, victory_threshold: float = 0.5):
    """Asks the agent for a final reflection on the mission."""
    threshold_pct = victory_threshold * 100
    reflection_prompt = f"""
{final_report}

[INSTRUCTION]
Analyze the Mission Report above.
1. Did you solve the task? (Survival Rate > {threshold_pct:.0f}% is considered a success).
2. What was the key to survival?
3. Why did some drones fail?
4. Final Conclusion.
"""
    print(f"\n{Colors.CYAN}[SYSTEM] Requesting Final Agent Reflection...{Colors.RESET}")
    
    # We need to ensure the agent doesn't stop immediately if the mission was marked complete
    # Force allow reflection by temporarily unsetting mission_complete if implementation allows,
    # or relying on the agent's logic to handle one last step.
    # In BaseHandler, we assume 'mission_complete' stops 'step', so we must reset it.
    agent.mission_complete = False 
    
    # We pass 'Proceed.' or the prompt directly? 
    # BaseHandler step takes user_input.
    agent.step(user_input=reflection_prompt)
