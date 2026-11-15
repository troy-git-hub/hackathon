"""Public feature labels only; never inspect or transmit prompt contents."""
import inspect
ALLOWED={'assistant','blackboard','quiz','grading','classroom','catchup','qa','review','summary','persona','booklet','problem_solving','vision'}
def infer(default='assistant'):
    frame=inspect.currentframe()
    try:
        frame=frame.f_back
        for _ in range(16):
            if frame is None:break
            module=frame.f_globals.get('__name__','');function=frame.f_code.co_name
            if module.startswith('echo.'):
                label=module.rsplit('.',1)[-1]
                if label in ('blackboard','quiz','persona','booklet','booklets'):return {'booklets':'booklet'}.get(label,label)
                if label in ('assessment','recall'):return 'grading'
                if label in ('context','awareness'):return 'classroom'
                if label in ('lesson_design','breakpoint'):return 'catchup'
                if label in ('lesson_ask','knowledge'):return 'qa'
                if any(word in function for word in ('solve','problem')):return 'problem_solving'
                if any(word in function for word in ('summary','summarize','echo_report')):return 'summary'
            frame=frame.f_back
    finally:del frame
    return default
