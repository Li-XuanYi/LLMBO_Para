"""Bounded direct rejection-feedback WarmStart, reusing the common archived runner."""
from run_prompt_warmstart import main

if __name__=='__main__':
    raise SystemExit(main(default_settings='agent-rejection-warmstart.json',default_output='runs/agent-rejection'))
