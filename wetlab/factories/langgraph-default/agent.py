"""A task-local LangGraph agent with the native SQLite checkpointer.

This is a concrete default graph for Harbor's project-based LangGraph harness.
"""
import json,os,subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph,MessagesState,END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

ROOT=Path('/logs/agent/langgraph-native')

@tool
def shell(command:str)->str:
    """Execute a shell command in the task container.

    Args:
        command: The shell command to execute.
    """
    r=subprocess.run(command,shell=True,capture_output=True,text=True,timeout=120)
    return r.stdout+r.stderr+'\nexit_code='+str(r.returncode)


def _messages(state):
    return [m.model_dump(mode='json') for m in state.values.get('messages',[])]


class NativeGraph:
    def __init__(self,compiled):self.compiled=compiled
    async def ainvoke(self,value,config):
        old=ROOT/'session.json'
        previous=json.loads(old.read_text()) if old.exists() else None
        restored=await self.compiled.aget_state(config)
        if previous and _messages(restored)!=previous['messages']:
            raise ValueError('LangGraph native checkpoint context was not restored')
        result=await self.compiled.ainvoke(value,config)
        state=await self.compiled.aget_state(config)
        data={'format':'wetlab-langgraph-native-v1','session_id':str(config['configurable']['thread_id']),
              'messages':_messages(state),'completed':not state.next,'checkpoint':state.config}
        tmp=old.with_suffix('.tmp');tmp.write_text(json.dumps(data));os.chmod(tmp,0o600);tmp.replace(old)
        return result


@asynccontextmanager
async def graph(config):
    ROOT.mkdir(parents=True,exist_ok=True)
    profile=json.loads((ROOT/'connection.json').read_text())
    model=ChatOpenAI(model=profile['model'],base_url=profile['base_url'],api_key=os.environ[profile['api_key_name']])
    model=model.bind_tools([shell])
    async def reason(state):
        result=await model.ainvoke([SystemMessage(content='Use task tools to follow the user instructions. End the turn after submitting an experiment; feedback arrives as a new user message.'),*state['messages']])
        return {'messages':[result]}
    builder=StateGraph(MessagesState);builder.add_node('reason',reason);builder.add_node('tools',ToolNode([shell]))
    builder.set_entry_point('reason')
    builder.add_conditional_edges('reason',lambda state:'tools' if state['messages'][-1].tool_calls else END)
    builder.add_edge('tools','reason')
    async with AsyncSqliteSaver.from_conn_string(str(ROOT/'checkpoints.sqlite')) as checkpointer:
        yield NativeGraph(builder.compile(checkpointer=checkpointer))
