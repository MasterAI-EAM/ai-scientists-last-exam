"""Authenticated, process-local Google GenerateContent to Chat Completions bridge.

The supplied endpoint and model are immutable. The bridge has no model fallback,
does not log HTTP paths or payloads, and keeps the provider key only in memory.
"""
from __future__ import annotations
import atexit, copy, hmac, json, threading, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class UnsupportedRequest(ValueError):
    pass


def _schema(value):
    if isinstance(value, list):return [_schema(v) for v in value]
    if not isinstance(value, dict):return value
    value={k:_schema(v) for k,v in value.items()}
    if isinstance(value.get('type'),str):value['type']=value['type'].lower()
    value.pop('propertyOrdering',None)  # presentation order, not schema semantics
    if value.pop('nullable',False):
        typ=value.get('type')
        if isinstance(typ,str):value['type']=[typ,'null']
        else:value={'anyOf':[value,{'type':'null'}]}
    return value


def to_chat(request, model):
    """Map full ordered native history, including reasoning and paired tool IDs."""
    if request.get('cachedContent'):
        raise UnsupportedRequest('Google-hosted cached context is unavailable on the configured provider')
    messages=[];pending=[];sequence=0
    system=request.get('systemInstruction') or request.get('system_instruction')
    if system:
        parts=system.get('parts',[]) if isinstance(system,dict) else [{'text':str(system)}]
        if any(set(p)-{'text'} for p in parts):raise UnsupportedRequest('non-text system instruction')
        messages.append({'role':'system','content':'\n'.join(p.get('text','') for p in parts)})
    for content in request.get('contents',[]):
        role=content.get('role','user');text=[];thought=[];calls=[];results=[]
        for part in content.get('parts',[]):
            if 'text' in part:
                (thought if part.get('thought') else text).append(part['text'])
            elif 'functionCall' in part:
                call=part['functionCall'];sequence+=1
                cid=call.get('id') or f'wetlab_call_{sequence}'
                calls.append({'id':cid,'type':'function','function':{'name':call['name'],'arguments':json.dumps(call.get('args',{}),ensure_ascii=False)}})
                pending.append((cid,call['name']))
            elif 'functionResponse' in part:
                response=part['functionResponse'];cid=response.get('id')
                if response.get('parts'):raise UnsupportedRequest('multimodal native tool results are unavailable on the configured provider')
                matches=[(i,p) for i,p in enumerate(pending) if (p[0]==cid if cid else p[1]==response['name'])]
                if not matches:raise UnsupportedRequest('unpaired native function response')
                index,pair=matches[0];pending.pop(index)
                results.append({'role':'tool','tool_call_id':pair[0],'content':json.dumps(response.get('response',{}),ensure_ascii=False)})
            else:raise UnsupportedRequest('unsupported non-text content part')
            # Gemini CLI inserts Google's documented unsigned-history bypass
            # when a non-Google provider returns ordinary tool calls. It carries
            # no hidden reasoning state. Genuine opaque signatures still fail.
            if part.get('thoughtSignature') and part['thoughtSignature'] not in (
                'skip_thought_signature_validator','c2tpcF90aG91Z2h0X3NpZ25hdHVyZV92YWxpZGF0b3I='):
                raise UnsupportedRequest('opaque Google thought signatures have no Chat Completions equivalent')
        if results:
            if calls or thought:raise UnsupportedRequest('mixed native tool result and assistant response')
            messages.extend(results)
        if text or calls or thought:
            item={'role':'assistant' if role=='model' else 'user','content':'\n'.join(text) or None}
            if calls:item['tool_calls']=calls
            if thought:item['reasoning_content']='\n'.join(thought)
            messages.append(item)
    if pending:raise UnsupportedRequest('native request has unresolved tool calls')
    result={'model':model,'messages':messages,'stream':False}
    tools=[]
    for group in request.get('tools',[]):
        unknown=set(group)-{'functionDeclarations','function_declarations'}
        if unknown:raise UnsupportedRequest('hosted Google tools are not available on the configured provider')
        for declaration in group.get('functionDeclarations',group.get('function_declarations',[])):
            function={'name':declaration['name'],'description':declaration.get('description',''),'parameters':_schema(declaration.get('parametersJsonSchema',declaration.get('parameters',{'type':'object','properties':{}})))}
            tools.append({'type':'function','function':function})
    if tools:result['tools']=tools
    config=request.get('generationConfig',{})
    for source,destination in [('temperature','temperature'),('topP','top_p'),('maxOutputTokens','max_tokens'),('stopSequences','stop'),('seed','seed'),('candidateCount','n')]:
        if source in config:result[destination]=config[source]
    if config.get('responseMimeType')=='application/json':
        schema=config.get('responseJsonSchema') or config.get('responseSchema')
        result['response_format']={'type':'json_schema','json_schema':{'name':'native_response','schema':_schema(schema)}} if schema else {'type':'json_object'}
    function_config=request.get('toolConfig',{}).get('functionCallingConfig',{})
    mode=function_config.get('mode','AUTO')
    if mode=='NONE':result['tool_choice']='none'
    elif mode=='ANY':
        allowed=function_config.get('allowedFunctionNames',[])
        if allowed:
            result['tools']=[t for t in tools if t['function']['name'] in allowed]
            if not result['tools']:raise UnsupportedRequest('no allowed functions are declared')
        result['tool_choice']='required'
    elif mode not in ('AUTO','VALIDATED'):raise UnsupportedRequest('unsupported native function calling mode')
    return result


def to_google(response, model):
    if not response.get('choices'):raise ValueError('provider response contains no candidates')
    candidates=[]
    for index,choice in enumerate(response.get('choices',[])):
        message=choice['message'];parts=[]
        if message.get('reasoning_content'):parts.append({'text':message['reasoning_content'],'thought':True})
        if message.get('content'):parts.append({'text':message['content']})
        for call in message.get('tool_calls',[]):
            arguments=call['function'].get('arguments') or '{}'
            try:arguments=json.loads(arguments) if isinstance(arguments,str) else arguments
            except json.JSONDecodeError as exc:raise ValueError('provider returned malformed function arguments') from exc
            parts.append({'functionCall':{'id':call['id'],'name':call['function']['name'],'args':arguments}})
        reason={'stop':'STOP','tool_calls':'STOP','length':'MAX_TOKENS','content_filter':'SAFETY'}.get(choice.get('finish_reason'),'STOP')
        candidates.append({'index':index,'content':{'role':'model','parts':parts},'finishReason':reason})
    usage=response.get('usage',{});thoughts=usage.get('completion_tokens_details',{}).get('reasoning_tokens',0)
    return {'candidates':candidates,'modelVersion':model,'responseId':response.get('id',''),
            'usageMetadata':{'promptTokenCount':usage.get('prompt_tokens',0),'candidatesTokenCount':max(0,usage.get('completion_tokens',0)-thoughts),'thoughtsTokenCount':thoughts,'totalTokenCount':usage.get('total_tokens',0)}}


class GoogleChatBridge:
    def __init__(self, *, upstream, key, model='deepseek/deepseek-flash', bind='0.0.0.0'):
        if model!='deepseek/deepseek-flash':raise ValueError('bridge model must be the authorized DeepSeek model')
        parsed=urllib.parse.urlparse(upstream)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('provider endpoint must be an authenticated HTTPS origin/path without embedded credentials')
        self.upstream=upstream.rstrip('/')+'/chat/completions';self.key=key;self.model=model
        self.requests=0;self.status_counts={};self.lock=threading.Lock()
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def _send(self,status,payload,sse=False):
                raw=('data: '+json.dumps(payload,ensure_ascii=False)+'\n\n').encode() if sse else json.dumps(payload,ensure_ascii=False).encode()
                self.send_response(status);self.send_header('Content-Type','text/event-stream' if sse else 'application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                with bridge.lock:bridge.status_counts[str(status)]=bridge.status_counts.get(str(status),0)+1
            def _authorized(self):
                parsed=urllib.parse.urlsplit(self.path)
                supplied=self.headers.get('x-goog-api-key') or urllib.parse.parse_qs(parsed.query).get('key',[''])[0]
                auth=self.headers.get('Authorization','')
                if not supplied and auth.startswith('Bearer '):supplied=auth[7:]
                return hmac.compare_digest(str(supplied).encode(),bridge.key.encode())
            def do_GET(self):
                if not self._authorized():return self._send(401,{'error':{'code':401,'message':'bridge authentication required','status':'UNAUTHENTICATED'}})
                path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                entry={'name':'models/'+bridge.model,'displayName':bridge.model,'inputTokenLimit':131072,'outputTokenLimit':8192,'supportedGenerationMethods':['generateContent','streamGenerateContent']}
                if path.rstrip('/').endswith('/models'):return self._send(200,{'models':[entry]})
                if path.endswith('/models/'+bridge.model):return self._send(200,entry)
                return self._send(404,{'error':{'code':404,'message':'unsupported bridge route'}})
            def do_POST(self):
                if not self._authorized():return self._send(401,{'error':{'code':401,'message':'bridge authentication required','status':'UNAUTHENTICATED'}})
                path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                stream=path.endswith(':streamGenerateContent')
                if not (stream or path.endswith(':generateContent')):return self._send(404,{'error':{'code':404,'message':'unsupported bridge route'}})
                selected=path.split('/models/',1)[-1].rsplit(':',1)[0]
                if selected!=bridge.model:return self._send(400,{'error':{'code':400,'message':'requested model differs from authorized model'}})
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=32*1024*1024:raise UnsupportedRequest('invalid request length')
                    native=json.loads(self.rfile.read(size));body=to_chat(native,bridge.model)
                    request=urllib.request.Request(bridge.upstream,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+bridge.key,'Content-Type':'application/json'})
                    with bridge.lock:bridge.requests+=1
                    with urllib.request.urlopen(request,timeout=300) as response:result=json.load(response)
                    self._send(200,to_google(result,bridge.model),sse=stream)
                except urllib.error.HTTPError as exc:
                    # Never echo the provider body: it may contain credential-bearing diagnostics.
                    self._send(exc.code,{'error':{'code':exc.code,'message':'configured provider returned HTTP '+str(exc.code),'status':'RESOURCE_EXHAUSTED' if exc.code in (402,429) else 'UNKNOWN'}})
                except (UnsupportedRequest,ValueError,KeyError) as exc:
                    self._send(400,{'error':{'code':400,'message':str(exc) if isinstance(exc,UnsupportedRequest) else 'malformed native or provider response','status':'INVALID_ARGUMENT'}})
                except Exception:
                    self._send(502,{'error':{'code':502,'message':'configured provider request failed','status':'UNAVAILABLE'}})
        self.server=ThreadingHTTPServer((bind,0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://host.docker.internal:'+str(self.server.server_port)
        atexit.register(self.close)
    def close(self):
        if self.server:
            server,self.server=self.server,None;server.shutdown();server.server_close()
    def evidence(self):
        return {'wire_model':self.model,'provider_requests':self.requests,'http_status_counts':copy.deepcopy(self.status_counts)}
