import getpass
import logging
import os
import time

from agent import BasicAgent
from agents.orchestrator import OrchestratorAgent
from llm_client import create_llm_client, list_available_models
from memory import SessionManager
from planning_agent import PlanningAgent

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("capybara.main")
from tools.basic_tools import _knowledge_store as global_knowledge_store


def select_provider_and_model():
    print("\n--- LLM Provider Selection ---")
    print("1. Ollama (Local)")
    print("2. OpenAI (Requires OPENAI_API_KEY)")
    print("3. Gemini (Requires GEMINI_API_KEY)")
    print("4. None (Phase 1 Keyword Matching)")
    
    provider_choice = input("Select provider (1-4): ").strip()
    
    if provider_choice == "4":
        return None, None
        
    providers = {"1": "ollama", "2": "openai", "3": "gemini"}
    provider_name = providers.get(provider_choice)
    
    if not provider_name:
        print("Invalid choice, defaulting to None.")
        return None, None

    # Check for required API keys
    api_key = None
    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            api_key = getpass.getpass("Enter your OpenAI API Key (or set OPENAI_API_KEY env var): ").strip()
    elif provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            api_key = getpass.getpass("Enter your Gemini API Key (or set GEMINI_API_KEY env var): ").strip()

    print(f"\nFetching available models for {provider_name}...")
    models = list_available_models(provider_name)
    
    if not models or models[0].startswith("("):
        # Could not fetch models or error returned
        print(f"⚠️ Could not query models from {provider_name}: {models[0] if models else 'Unknown error'}")
        if provider_name == "ollama":
            print("💡 Tip: Ensure Ollama is running locally (e.g. start the Ollama desktop app).")
        default_model = "qwen3.5:4b" if provider_name == "ollama" else ("gpt-4o" if provider_name == "openai" else "gemini-2.0-flash")
        manual_input = input(f"Enter model name manually [Default: {default_model}]: ").strip()
        if manual_input.isdigit() and int(manual_input) == 1:
            model_name = default_model
        else:
            model_name = manual_input or default_model
    else:
        print("\n--- Model Selection ---")
        default_idx = 1
        for i, model in enumerate(models, 1):
            if "qwen" in model.lower():
                default_idx = i
            print(f"{i}. {model}")
        model_choice = input(f"Select model (1-{len(models)}) [Default: {default_idx}]: ").strip() or str(default_idx)
        
        try:
            model_index = int(model_choice) - 1
            model_name = models[model_index]
        except (ValueError, IndexError):
            print(f"Invalid choice, defaulting to {models[default_idx - 1]}")
            model_name = models[default_idx - 1]

    return create_llm_client(provider_name, model_name, api_key), provider_name

def legacy_main():
    try:
        with open("asciiCapy.txt", "r", encoding="utf-8") as f:
            print(f.read())
    except FileNotFoundError:
        pass

    banner = r"""
 #####                                                        #                               
#     #   ##   #####  #   # #####    ##   #####    ##        # #    ####  ###### #    # ##### 
#        #  #  #    #  # #  #    #  #  #  #    #  #  #      #   #  #    # #      ##   #   #   
#       #    # #    #   #   #####  #    # #    # #    #    #     # #      #####  # #  #   #   
#       ###### #####    #   #    # ###### #####  ######    ####### #  ### #      #  # #   #   
#     # #    # #        #   #    # #    # #   #  #    #    #     # #    # #      #   ##   #   
 #####  #    # #        #   #####  #    # #    # #    #    #     #  ####  ###### #    #   #  
"""
    print(banner)
    
    llm_client, provider_name = select_provider_and_model()
    
    if llm_client:
        logger.info(f"\n✅ Initialized agent with {provider_name} ({llm_client.model})")
    else:
        logger.info("\n⚠️ No LLM selected. Running in Phase 1 (Keyword) mode.")
        
    print("-" * 40)
    
    # --- Session Management Menu ---
    session_manager = SessionManager()
    sessions = session_manager.list_sessions()
    
    # We will load memory into this variable if resuming
    loaded_memory = []
    
    print("\n--- Session Management ---")
    if sessions:
        print("Previous sessions found! You can resume or start fresh.")
        print("0. Start a NEW session")
        for i, s in enumerate(sessions[:5], 1): # show top 5
            print(f"{i}. Resume session from {s['id']} (Turns: {s['turn_count']} | Preview: {s['preview']})")
            
        choice = input(f"Select option (0-{min(len(sessions), 5)}): ").strip()
        try:
            choice_idx = int(choice)
            max_choice = min(len(sessions), 5)
            if choice_idx > 0 and choice_idx <= max_choice:
                selected = sessions[choice_idx - 1]
                loaded_memory = session_manager.load_session(selected["filepath"])
                logger.info(f"✅ Loaded session with {len(loaded_memory)} messages.")
            else:
                logger.info("Starting new session.")
                session_manager.start_new_session()
        except ValueError:
            logger.info("Invalid choice. Starting new session.")
            session_manager.start_new_session()
    else:
        logger.info("No previous sessions found. Starting fresh.")
        session_manager.start_new_session()
        
from prompt_loader import check_and_extract_file_path, load_prompts_from_file
from tal_test_report import format_batch_summary, format_comparison_table
from tal_test_runner import TALTestRunner


def persist_agent_session(session_manager, agent, fallback_agent, llm_client, provider_name, tal_mode):
    """Persist the active architecture's memory and TAL event log."""
    session_memory = getattr(agent, "memory", None)
    if session_memory is None and hasattr(agent, "basic_agent"):
        session_memory = agent.basic_agent.memory
    if session_memory is None:
        session_memory = fallback_agent.memory

    event_log = None
    if tal_mode:
        event_log = getattr(agent, "event_log", None)
        if event_log is None and hasattr(agent, "basic_agent"):
            event_log = getattr(agent.basic_agent, "event_log", None)

    session_manager.auto_save(
        memory=session_memory,
        metadata={
            "model": getattr(llm_client, "model", "None"),
            "provider": provider_name,
            "tal_mode": tal_mode,
        },
        event_log=event_log,
    )


def run_tal_test_cli(llm_client, provider_name, default_prompt_file=None):
    """Runs TAL Test Mode CLI for interactive or batch A/B evaluation."""
    if not llm_client:
        print("Error: TAL Test Mode requires an active LLM provider.")
        return

    print("\n" + "=" * 50)
    print("      🧪 CAPYBARA TAL TEST MODE (A/B) 🧪")
    print("=" * 50)
    print("Runs any prompt TWICE: once with TAL, once without.")
    print("Gathers steps, execution time, tokens, tool usage, gate blocks, and verification.\n")
    
    print("--- Select Agent Architecture to Test ---")
    print("1. ReAct Mode (BasicAgent)")
    print("2. Planning Mode (PlanningAgent)")
    print("3. Multi-Agent Mode (OrchestratorAgent)")
    arch_choice = input("Select architecture (1, 2, or 3) [Default 1]: ").strip() or "1"
    
    arch_map = {"1": "react", "2": "planning", "3": "multi-agent"}
    mode = arch_map.get(arch_choice, "react")
    
    verbose_in = input("Show verbose agent logs during run? (y/N): ").strip().lower()
    verbose = verbose_in == 'y'

    runner = TALTestRunner(
        llm_client=llm_client,
        mode=mode,
        verbose=verbose,
        knowledge_store=global_knowledge_store
    )

    if default_prompt_file:
        input_mode = "2"
        filepath = default_prompt_file
    else:
        print("\n--- Test Input Mode ---")
        print("1. Single Interactive Prompt Loop (Supports typing text or 'load <file.json>')")
        print("2. Load Prompts from File (.json / .txt)")
        input_mode = input("Select input mode (1 or 2) [Default 1]: ").strip() or "1"
        filepath = None
    
    if input_mode == "2":
        if not filepath:
            filepath = input("Enter path to prompts file (e.g. data/sample_prompts.json or prompts.txt): ").strip()
        
        try:
            prompt_items = load_prompts_from_file(filepath)
        except Exception as e:
            print(f"Error loading prompt file: {e}")
            return
            
        print(f"\n✅ Loaded {len(prompt_items)} prompt(s) from '{filepath}'.")
        
        # If multiple prompts, ask whether to run all or select one
        selected_prompts = []
        if len(prompt_items) > 1:
            print("\nAvailable Prompts in File:")
            for i, p in enumerate(prompt_items, 1):
                preview = p['prompt'][:70].replace('\n', ' ')
                print(f"  {i}. [{p['title']}] {preview}...")
            print(f"  A. Run ALL ({len(prompt_items)} prompts in batch)")
            
            choice = input(f"\nSelect prompt to test (1-{len(prompt_items)} or 'A' for all) [Default A]: ").strip().upper() or "A"
            if choice == "A":
                selected_prompts = [p["prompt"] for p in prompt_items]
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(prompt_items):
                        selected_prompts = [prompt_items[idx]["prompt"]]
                    else:
                        print("Invalid selection, running all.")
                        selected_prompts = [p["prompt"] for p in prompt_items]
                except ValueError:
                    selected_prompts = [p["prompt"] for p in prompt_items]
        else:
            selected_prompts = [prompt_items[0]["prompt"]]

        if len(selected_prompts) == 1:
            prompt = selected_prompts[0]
            print("\n⏳ Executing single prompt A/B comparison...")
            print(f"Prompt: {prompt}\n")
            result = runner.run_single_test(prompt)
            print("\n" + format_comparison_table(result))
            print("💾 Result saved to data/tal_tests/")
        else:
            print(f"\nStarting batch evaluation of {len(selected_prompts)} prompts...")
            def on_prog(i, tot, res):
                print(f"\n[{i}/{tot}] Completed prompt: {res.prompt[:40]}...")
                print(format_comparison_table(res))
                
            results = runner.run_batch_test(selected_prompts, on_progress=on_prog)
            print("\n" + format_batch_summary(results))
            print("\n✅ Batch test complete. Results saved in data/tal_tests/")
    else:
        print("\nType your prompt to run the A/B test, or load from file (e.g. 'load sample_prompts.json' or '@prompts.json').")
        print("Type 'exit' or 'quit' to return.")
        while True:
            try:
                user_input = input("\n[TAL-Test] Prompt: ").strip()
            except (KeyboardInterrupt, EOFError):
                break
                
            if user_input.lower() in ("exit", "quit"):
                break
                
            if not user_input:
                continue

            # Check if user entered a file loading command or .json file
            extracted_path = check_and_extract_file_path(user_input)
            if extracted_path:
                try:
                    loaded_items = load_prompts_from_file(extracted_path)
                    print(f"📄 Loaded {len(loaded_items)} prompt(s) from '{extracted_path}'.")
                    if len(loaded_items) == 1:
                        prompt = loaded_items[0]["prompt"]
                        print(f"Prompt: {prompt}\n")
                    else:
                        for idx, p in enumerate(loaded_items, 1):
                            print(f"  {idx}. [{p['title']}] {p['prompt'][:60]}...")
                        sel = input(f"Select prompt (1-{len(loaded_items)}) [Default 1]: ").strip() or "1"
                        sel_idx = max(0, min(len(loaded_items) - 1, int(sel) - 1)) if sel.isdigit() else 0
                        prompt = loaded_items[sel_idx]["prompt"]
                        print(f"Selected: {prompt}\n")
                except Exception as e:
                    print(f"⚠️ Could not load prompt file '{extracted_path}': {e}")
                    continue
            else:
                prompt = user_input
                
            print("\n⏳ Executing A/B comparison (Baseline vs TAL)...")
            result = runner.run_single_test(prompt)
            print("\n" + format_comparison_table(result))
            print("💾 Result saved to data/tal_tests/")

def main():
    import sys
    tal_test_flag = "--tal-test" in sys.argv
    prompt_file_arg = None
    if "--prompt-file" in sys.argv:
        idx = sys.argv.index("--prompt-file")
        if idx + 1 < len(sys.argv):
            prompt_file_arg = sys.argv[idx + 1]

    try:
        with open("asciiCapy.txt", "r", encoding="utf-8") as f:
            print(f.read())
    except FileNotFoundError:
        pass

    banner = r"""
 #####                                                        #                               
#     #   ##   #####  #   # #####    ##   #####    ##        # #    ####  ###### #    # ##### 
#        #  #  #    #  # #  #    #  #  #  #    #  #  #      #   #  #    # #      ##   #   #   
#       #    # #    #   #   #####  #    # #    # #    #    #     # #      #####  # #  #   #   
#       ###### #####    #   #    # ###### #####  ######    ####### #  ### #      #  # #   #   
#     # #    # #        #   #    # #    # #   #  #    #    #     # #    # #      #   ##   #   
 #####  #    # #        #   #####  #    # #    # #    #    #     #  ####  ###### #    #   #  
"""
    print(banner)
    
    llm_client, provider_name = select_provider_and_model()
    
    if llm_client:
        logger.info(f"\n✅ Initialized agent with {provider_name} ({llm_client.model})")
    else:
        logger.info("\n⚠️ No LLM selected. Running in Phase 1 (Keyword) mode.")
        
    print("-" * 40)

    if tal_test_flag:
        run_tal_test_cli(llm_client, provider_name, default_prompt_file=prompt_file_arg)
        return
    
    # --- Session Management Menu ---
    session_manager = SessionManager()
    sessions = session_manager.list_sessions()
    
    # We will load memory into this variable if resuming
    loaded_memory = []
    
    print("\n--- Session Management ---")
    if sessions:
        print("Previous sessions found! You can resume or start fresh.")
        print("0. Start a NEW session")
        for i, s in enumerate(sessions[:5], 1): # show top 5
            print(f"{i}. Resume session from {s['id']} (Turns: {s['turn_count']} | Preview: {s['preview']})")
            
        choice = input(f"Select option (0-{min(len(sessions), 5)}): ").strip()
        try:
            choice_idx = int(choice)
            max_choice = min(len(sessions), 5)
            if choice_idx > 0 and choice_idx <= max_choice:
                selected = sessions[choice_idx - 1]
                loaded_memory = session_manager.load_session(selected["filepath"])
                logger.info(f"✅ Loaded session with {len(loaded_memory)} messages.")
            else:
                logger.info("Starting new session.")
                session_manager.start_new_session()
        except ValueError:
            logger.info("Invalid choice. Starting new session.")
            session_manager.start_new_session()
    else:
        logger.info("No previous sessions found. Starting fresh.")
        session_manager.start_new_session()
        
    print("-" * 40)
    
    print("\n--- Mode Selection ---")
    print("1. ReAct Mode (Phase 3 - Quick, reactive)")
    print("2. Planning Mode (Phase 4 - Plan-and-execute for complex goals)")
    print("3. Multi-Agent Mode (Phase 8 - Orchestrator delegates to specialists)")
    mode_choice = input("Select mode (1, 2, or 3): ").strip()
    
    arch_map = {"1": "react", "2": "planning", "3": "multi-agent"}
    mode_name = arch_map.get(mode_choice, "react")
    if not llm_client and mode_choice in ("2", "3"):
        logger.info("Offline keyword mode only supports ReAct mode; switching to ReAct.")
        mode_choice = "1"
        mode_name = "react"
    
    print("-" * 40)
    
    verbose_input = input("Enable verbose mode to see the agent's reasoning? (Y/n): ").strip().lower()
    verbose = verbose_input != 'n'
    
    guardrails_input = input("Enable guardrails? (Confirms dangerous actions) (Y/n): ").strip().lower()
    guardrails = guardrails_input != 'n'
    
    reflection_input = input("Enable self-reflection? (Agent reviews its own answers) (y/N): ").strip().lower()
    reflection = reflection_input == 'y'

    tal_test_input = input("Enable TAL Test Mode? (A/B effectiveness test: runs each prompt with and without TAL) (y/N): ").strip().lower()
    tal_test_enabled = tal_test_input == 'y'

    if not tal_test_enabled:
        tal_input = input("Enable TAL Mode? (Task Abstraction Language protocol & verification) (Y/n): ").strip().lower()
        tal_mode = tal_input != 'n'
    else:
        tal_mode = False
        logger.info("\n🧪 TAL Test Mode enabled: each prompt will run both with and without TAL.")
    
    print("-" * 40)
    print("Type 'help' to see what I can do.")
    print("Type 'load <file.json>' or '@<file.json>' to load prompts from file.")
    print("Type 'exit' or 'quit' to stop.")
    print("-" * 40)
    
    # Initialize TALTestRunner if in TAL test mode
    tal_test_runner = None
    if tal_test_enabled and llm_client:
        tal_test_runner = TALTestRunner(
            llm_client=llm_client,
            mode=mode_name,
            verbose=verbose,
            guardrails_enabled=guardrails,
            reflection_enabled=reflection,
            knowledge_store=global_knowledge_store
        )

    # Initialize our base agent (fallback for mode 1 and 2)
    basic_agent = BasicAgent(
        llm_client=llm_client,
        system_prompt="You are a helpful AI assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally.",
        verbose=verbose,
        knowledge_store=global_knowledge_store,
        guardrails_enabled=guardrails,
        reflection_enabled=reflection,
        tal_mode=tal_mode
    )
    
    # Inject loaded memory if resuming
    if loaded_memory:
        basic_agent.memory = loaded_memory
    
    # Wrap it in PlanningAgent or Orchestrator if requested
    if mode_choice == "2":
        my_agent = PlanningAgent(basic_agent, llm_client, tal_mode=tal_mode)
    elif mode_choice == "3":
        my_agent = OrchestratorAgent(
            llm_client=llm_client,
            verbose=verbose,
            knowledge_store=global_knowledge_store,
            guardrails_enabled=guardrails,
            reflection_enabled=reflection,
            tal_mode=tal_mode
        )
    else:
        my_agent = basic_agent

    if loaded_memory and hasattr(my_agent, "memory"):
        my_agent.memory = loaded_memory

    # If --prompt-file was provided in non-tal mode, execute it directly
    if prompt_file_arg:
        try:
            loaded_items = load_prompts_from_file(prompt_file_arg)
            print(f"\n📄 Loaded {len(loaded_items)} prompt(s) from '{prompt_file_arg}'.")
            for item in loaded_items:
                prompt_text = item["prompt"]
                pipeline_obj = item.get("pipeline")
                print(f"\n--- Running [{item['title']}]: {prompt_text[:70]}... ---")
                start_time = time.time()
                if pipeline_obj and hasattr(my_agent, "run_pipeline"):
                    resp = my_agent.run_pipeline(pipeline_obj)
                elif mode_choice in ("2", "3"):
                    resp = my_agent.run(pipeline_obj if pipeline_obj else prompt_text)
                else:
                    resp = my_agent.run_turn(prompt_text)
                elapsed_time = time.time() - start_time
                logger.info(f"Capybara: {resp}")

                if tal_mode and hasattr(my_agent, "generate_feedback_report"):
                    try:
                        from tal.feedback_report import format_feedback_card, save_feedback_report
                        report = my_agent.generate_feedback_report(prompt_text, resp, duration_seconds=elapsed_time)
                        print("\n" + format_feedback_card(report))
                        json_path, _ = save_feedback_report(report)
                        print(f"💾 Feedback report saved to {json_path}")
                    except Exception as e:
                        logger.debug(f"Feedback report generation skipped: {e}")
                persist_agent_session(
                    session_manager=session_manager,
                    agent=my_agent,
                    fallback_agent=basic_agent,
                    llm_client=llm_client,
                    provider_name=provider_name,
                    tal_mode=tal_mode,
                )
            return
        except Exception as e:
            print(f"Error loading prompt file '{prompt_file_arg}': {e}")
    
    # The Agent Loop
    while True:
        try:
            user_input = input("\nYou: ")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
            
        if user_input.lower().strip() in ["exit", "quit"]:
            print("Capybara: Goodbye!")
            break
            
        if not user_input.strip():
            continue

        # Check if user entered a file loading command or .json file
        extracted_path = check_and_extract_file_path(user_input)
        if extracted_path:
            try:
                loaded_items = load_prompts_from_file(extracted_path)
                print(f"\n📄 Loaded {len(loaded_items)} prompt(s) from '{extracted_path}'.")
                if len(loaded_items) == 1:
                    selected_item = loaded_items[0]
                else:
                    for idx, p in enumerate(loaded_items, 1):
                        print(f"  {idx}. [{p['title']}] {p['prompt'][:60]}...")
                    sel = input(f"Select prompt (1-{len(loaded_items)}) [Default 1]: ").strip() or "1"
                    sel_idx = max(0, min(len(loaded_items) - 1, int(sel) - 1)) if sel.isdigit() else 0
                    selected_item = loaded_items[sel_idx]
                
                prompt_to_run = selected_item["prompt"]
                print(f"\nSelected: {prompt_to_run}\n")
                if selected_item.get("is_pipeline") and selected_item.get("pipeline"):
                    user_input = selected_item["pipeline"]
                else:
                    user_input = prompt_to_run
            except Exception as e:
                print(f"⚠️ Could not load prompt file '{extracted_path}': {e}")
                continue
            
        if tal_test_enabled and tal_test_runner:
            print("\n⏳ Executing A/B comparison (Baseline vs TAL)...")
            test_result = tal_test_runner.run_single_test(user_input)
            print("\n" + format_comparison_table(test_result))
            print("💾 Result saved to data/tal_tests/")
            continue

        start_turn_time = time.time()
        if mode_choice in ("2", "3"):
            response = my_agent.run(user_input)
        else:
            response = my_agent.run_turn(user_input)
        elapsed_turn_time = time.time() - start_turn_time
            
        logger.info(f"Capybara: {response}")
        
        # Display & save TAL performance feedback report
        if tal_mode and hasattr(my_agent, "generate_feedback_report"):
            try:
                from tal.feedback_report import format_feedback_card, save_feedback_report
                report = my_agent.generate_feedback_report(user_input, response, duration_seconds=elapsed_turn_time)
                print("\n" + format_feedback_card(report))
                json_path, _ = save_feedback_report(report)
                print(f"💾 Feedback report saved to {json_path}")
            except Exception as e:
                logger.debug(f"Feedback report generation skipped: {e}")

        # Auto-save after each turn using the active architecture's state.
        persist_agent_session(
            session_manager=session_manager,
            agent=my_agent,
            fallback_agent=basic_agent,
            llm_client=llm_client,
            provider_name=provider_name,
            tal_mode=tal_mode,
        )

if __name__ == "__main__":
    main()
