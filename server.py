#!/usr/bin/env python3
"""HackWave: dependency-free SQLite hackathon application. Python 3.10+."""
import os, json, sqlite3, secrets, hashlib, hmac, mimetypes, re, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from http.cookies import SimpleCookie

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('HACKWAVE_DB',str(ROOT/'hackwave.db')))
HOST=os.environ.get('HOST','127.0.0.1'); PORT=int(os.environ.get('PORT','8000'))
LOCK=threading.RLock()
RUBRIC={'Innovation':20,'Technical Implementation':25,'Problem Relevance':20,'Prototype':20,'Presentation':15}

def utc_now(): return datetime.now(timezone.utc)
def stamp(d): return d.isoformat(timespec='seconds').replace('+00:00','Z')
def hash_pw(p,s=None):
    s=s or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),260000).hex()
    return f'{s}${digest}'
def check_pw(p,record):
    try:
        s,expected=record.split('$'); return hmac.compare_digest(hash_pw(p,s),record)
    except Exception:return False

def db():
    c=sqlite3.connect(DB,timeout=15,check_same_thread=False)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');return c

def initialize():
    with LOCK,db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','reviewer','team')));
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),event_name TEXT NOT NULL,start_at TEXT NOT NULL,end_at TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS problems(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,college TEXT NOT NULL,leader_id INTEGER NOT NULL REFERENCES users(id),problem_id INTEGER NOT NULL REFERENCES problems(id),project TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY,team_id INTEGER NOT NULL REFERENCES teams(id),name TEXT NOT NULL,email TEXT NOT NULL,department TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rounds(id INTEGER PRIMARY KEY,name TEXT NOT NULL,weight INTEGER NOT NULL CHECK(weight BETWEEN 0 AND 100));
        CREATE TABLE IF NOT EXISTS assignments(round_id INTEGER NOT NULL REFERENCES rounds(id),team_id INTEGER NOT NULL REFERENCES teams(id),reviewer_id INTEGER NOT NULL REFERENCES users(id),PRIMARY KEY(round_id,team_id,reviewer_id));
        CREATE TABLE IF NOT EXISTS scores(round_id INTEGER NOT NULL,team_id INTEGER NOT NULL,reviewer_id INTEGER NOT NULL,innovation INTEGER NOT NULL,technical INTEGER NOT NULL,relevance INTEGER NOT NULL,prototype INTEGER NOT NULL,presentation INTEGER NOT NULL,feedback TEXT NOT NULL DEFAULT '',submitted_at TEXT NOT NULL,PRIMARY KEY(round_id,team_id,reviewer_id),FOREIGN KEY(round_id,team_id,reviewer_id) REFERENCES assignments(round_id,team_id,reviewer_id));
        CREATE TABLE IF NOT EXISTS schedule(id INTEGER PRIMARY KEY,title TEXT NOT NULL,starts_at TEXT NOT NULL,location TEXT NOT NULL,details TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor INTEGER,action TEXT NOT NULL,details TEXT NOT NULL,at TEXT NOT NULL);
        ''')
        if c.execute('SELECT COUNT(*) FROM settings').fetchone()[0]:return
        start=utc_now()+timedelta(hours=2); end=start+timedelta(hours=24)
        c.execute('INSERT INTO settings VALUES(1,?,?,?,0)',('HackWave 2026',stamp(start),stamp(end)))
        for title,desc in [('AI Cyber Threat Detection','Develop AI-based tools for detecting network anomalies.'),('Smart Agriculture','Build intelligent solutions for sustainable farming.'),('Smart Tourism','Design smart, accessible and sustainable travel experiences.'),('Digital Healthcare','Innovate for early detection and accessible care.'),('Smart Cities & IoT','Solve practical urban challenges with connected systems.')]:c.execute('INSERT INTO problems(title,description) VALUES(?,?)',(title,desc))
        password=os.environ.get('HACKWAVE_DEMO_PASSWORD','Demo@12345')
        for name,email,role in [('Event Admin','admin@hackwave.local','admin')]+[(f'Judge {i}',f'judge{i}@hackwave.local','reviewer') for i in range(1,6)]:c.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(name,email,hash_pw(password),role))
        for i in range(1,8):
            email=f'team{i}@hackwave.local'; c.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(f'Team Lead {i}',email,hash_pw(password),'team'))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO teams(name,college,leader_id,problem_id,project,status,created_at) VALUES(?,?,?,?,?,?,?)',('Team '+['Nova','Quantum','CyberX','AgroAI','Orbit','CodeSpark','Astra'][i-1],'Demo Engineering College',uid,1+(i-1)%5,f'Prototype {i}','approved',stamp(utc_now())))
        for i,name,weight in [(1,'Ideation Review',20),(2,'Prototype Review',30),(3,'Final Review',50)]:c.execute('INSERT INTO rounds(id,name,weight) VALUES(?,?,?)',(i,name,weight))
        for t in c.execute('SELECT id FROM teams').fetchall():
            for r in range(1,4):
                for judge in c.execute("SELECT id FROM users WHERE role='reviewer'").fetchall():c.execute('INSERT INTO assignments VALUES(?,?,?)',(r,t['id'],judge['id']))
        events=[('Registration & Check-in',-1,'Main Hall'),('Opening Ceremony',0,'Auditorium'),('Hackathon Begins',0.5,'Innovation Lab'),('Review 1',5,'Innovation Lab'),('Mentoring Session',9,'Innovation Lab'),('Review 2',14,'Innovation Lab'),('Review 3',22,'Innovation Lab'),('Hackathon Ends',24.5,'Main Hall'),('Results & Awards',25,'Auditorium')]
        for title,offset,loc in events:c.execute('INSERT INTO schedule(title,starts_at,location,details) VALUES(?,?,?,?)',(title,stamp(start+timedelta(hours=offset)),loc,''))

def rows(c,query,args=()):return [dict(r) for r in c.execute(query,args).fetchall()]
def body_json(handler):
    n=int(handler.headers.get('Content-Length','0'))
    if n>200000:raise ValueError('Request too large')
    return json.loads(handler.rfile.read(n) or b'{}')
def require(data,field,max_len=150):
    v=str(data.get(field,'')).strip()
    if not v or len(v)>max_len:raise ValueError(f'Invalid {field}')
    return v

def leaderboards(c):
    rounds=rows(c,'SELECT * FROM rounds ORDER BY id')
    teams=rows(c,"SELECT t.id,t.name,t.college,t.project,t.problem_id,p.title problem FROM teams t JOIN problems p ON p.id=t.problem_id WHERE t.status='approved'")
    for t in teams:
        t['rounds']={};t['total']=0;t['complete']=True
        for r in rounds:
            scores=rows(c,'SELECT innovation+technical+relevance+prototype+presentation AS mark FROM scores WHERE team_id=? AND round_id=?',(t['id'],r['id']))
            required=c.execute('SELECT COUNT(*) FROM assignments WHERE team_id=? AND round_id=?',(t['id'],r['id'])).fetchone()[0]
            complete=required>0 and len(scores)==required
            avg=round(sum(s['mark'] for s in scores)/len(scores),2) if scores else None
            t['rounds'][str(r['id'])]={'average':avg,'received':len(scores),'required':required,'complete':complete}
            if not complete:t['complete']=False
            if complete:t['total']+=avg*r['weight']/100
        t['total']=round(t['total'],2) if t['complete'] else None
    teams.sort(key=lambda t:(t['total'] is None,-(t['total'] or 0),t['name'].lower()))
    rank=0;last=None
    for i,t in enumerate(teams):
        if t['total'] is not None:
            if t['total']!=last:rank=i+1;last=t['total']
            t['rank']=rank
        else:t['rank']=None
    for pid in set(t['problem_id'] for t in teams):
        subset=[t for t in teams if t['problem_id']==pid and t['complete']]
        last=None;rank=0
        for i,t in enumerate(subset):
            if t['total']!=last:rank=i+1;last=t['total']
            t['problem_rank']=rank
    return teams

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,status=200,obj=None,headers=None):
        data=json.dumps(obj if obj is not None else {}).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def auth(self,c):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return None
        token=cookie.get('hackwave_session')
        if not token:return None
        return c.execute('SELECT u.id,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.value.encode()).hexdigest(),stamp(utc_now()))).fetchone()
    def do_GET(self):
        path=urlparse(self.path).path
        if path.startswith('/api/'):
            try:
                with db() as c:
                    user=self.auth(c)
                    if path=='/api/bootstrap':
                        settings=dict(c.execute('SELECT * FROM settings').fetchone())
                        payload={'settings':settings,'problems':rows(c,'SELECT * FROM problems'),'schedule':rows(c,'SELECT * FROM schedule ORDER BY starts_at'),'rounds':rows(c,'SELECT * FROM rounds ORDER BY id'),'leaderboard':leaderboards(c) if settings['published'] else [],'published':bool(settings['published']),'me':dict(user) if user else None}
                        if user:payload['me'].pop('csrf',None)
                        return self.send(obj=payload)
                    if path=='/api/me':return self.send(obj={'user':dict(user) if user else None})
                    if not user:return self.send(401,{'error':'Sign in required'})
                    if path=='/api/dashboard':
                        if user['role']=='admin':
                            out={'teams':rows(c,'SELECT t.*,p.title problem,u.email leader_email FROM teams t JOIN problems p ON p.id=t.problem_id JOIN users u ON u.id=t.leader_id ORDER BY t.id DESC'),'users':rows(c,'SELECT id,name,email,role FROM users'),'assignments':rows(c,'SELECT * FROM assignments'),'scores':rows(c,'SELECT * FROM scores'),'leaderboard':leaderboards(c)}
                        elif user['role']=='reviewer':
                            out={'assignments':rows(c,'SELECT a.*,t.name team_name,t.project,p.title problem,r.name round_name,s.innovation,s.technical,s.relevance,s.prototype,s.presentation,s.feedback FROM assignments a JOIN teams t ON t.id=a.team_id JOIN problems p ON p.id=t.problem_id JOIN rounds r ON r.id=a.round_id LEFT JOIN scores s ON s.round_id=a.round_id AND s.team_id=a.team_id AND s.reviewer_id=a.reviewer_id WHERE a.reviewer_id=? AND t.status=\'approved\' ORDER BY r.id,t.name',(user['id'],))}
                        else:out={'teams':rows(c,'SELECT t.*,p.title problem FROM teams t JOIN problems p ON p.id=t.problem_id WHERE t.leader_id=?',(user['id'],))}
                        return self.send(obj=out)
                self.send(404,{'error':'Not found'})
            except Exception:return self.send(500,{'error':'Server error'})
        else:
            if path=='/':path='/index.html'
            target=(ROOT/'static'/path.lstrip('/')).resolve()
            if not target.is_relative_to((ROOT/'static').resolve()) or not target.is_file():return self.send(404,{'error':'Not found'})
            data=target.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            data=body_json(self)
            with LOCK,db() as c:
                user=self.auth(c)
                if path=='/api/login':
                    email=require(data,'email').lower();password=require(data,'password',200)
                    u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                    if not u or not check_pw(password,u['password']):return self.send(401,{'error':'Invalid email or password'})
                    token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(24)
                    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,stamp(utc_now()+timedelta(hours=12))))
                    return self.send(obj={'ok':True,'csrf':csrf},headers={'Set-Cookie':f'hackwave_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'+('; Secure' if self.headers.get('X-Forwarded-Proto')=='https' else '')})
                if path=='/api/register':
                    name=require(data,'name');email=require(data,'email').lower();password=require(data,'password',200)
                    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(password)<10:raise ValueError('Enter a valid email and password of 10+ characters')
                    team=require(data,'team');college=require(data,'college');project=require(data,'project');pid=int(data.get('problem_id',0))
                    if not c.execute('SELECT id FROM problems WHERE id=?',(pid,)).fetchone():raise ValueError('Select a problem statement')
                    if c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():raise ValueError('Email already registered')
                    c.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(name,email,hash_pw(password),'team'))
                    uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.execute('INSERT INTO teams(name,college,leader_id,problem_id,project,created_at) VALUES(?,?,?,?,?,?)',(team,college,uid,pid,project,stamp(utc_now())))
                    tid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.execute('INSERT INTO members(team_id,name,email,department) VALUES(?,?,?,?)',(tid,name,email,str(data.get('department',''))[:120]))
                    return self.send(201,{'ok':True,'team_id':tid})
                if not user:return self.send(401,{'error':'Sign in required'})
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']):return self.send(403,{'error':'Invalid CSRF token. Sign in again.'})
                if path=='/api/logout':
                    cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
                    if cookie.get('hackwave_session'):c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(cookie['hackwave_session'].value.encode()).hexdigest(),))
                    return self.send(obj={'ok':True},headers={'Set-Cookie':'hackwave_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
                if path=='/api/score':
                    if user['role']!='reviewer':return self.send(403,{'error':'Reviewer only'})
                    rid=int(data.get('round_id',0));tid=int(data.get('team_id',0))
                    if not c.execute('SELECT 1 FROM assignments WHERE round_id=? AND team_id=? AND reviewer_id=?',(rid,tid,user['id'])).fetchone():return self.send(403,{'error':'Not assigned'})
                    vals=[]
                    for key,maxi in [('innovation',20),('technical',25),('relevance',20),('prototype',20),('presentation',15)]:
                        v=int(data.get(key,-1))
                        if v<0 or v>maxi:raise ValueError(f'{key} must be 0–{maxi}')
                        vals.append(v)
                    feedback=str(data.get('feedback',''))[:2000]
                    try:c.execute('INSERT INTO scores VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,tid,user['id'],*vals,feedback,stamp(utc_now())))
                    except sqlite3.IntegrityError:return self.send(409,{'error':'Already submitted; contact an admin for a correction'})
                    c.execute('INSERT INTO audit(actor,action,details,at) VALUES(?,?,?,?)',(user['id'],'score_submitted',f'round={rid};team={tid}',stamp(utc_now())))
                    return self.send(obj={'ok':True,'total':sum(vals)})
                if user['role']!='admin':return self.send(403,{'error':'Admin only'})
                if path=='/api/team-status':
                    tid=int(data.get('team_id',0));status=str(data.get('status',''))
                    if status not in ('approved','pending','rejected'):raise ValueError('Invalid status')
                    c.execute('UPDATE teams SET status=? WHERE id=?',(status,tid))
                    if status=='approved':
                        for round_row in c.execute('SELECT id FROM rounds').fetchall():
                            for reviewer in c.execute("SELECT id FROM users WHERE role='reviewer'").fetchall():
                                c.execute('INSERT OR IGNORE INTO assignments(round_id,team_id,reviewer_id) VALUES(?,?,?)',(round_row['id'],tid,reviewer['id']))
                    return self.send(obj={'ok':True})
                if path=='/api/publish':
                    c.execute('UPDATE settings SET published=? WHERE id=1',(int(bool(data.get('published'))),));return self.send(obj={'ok':True})
                if path=='/api/settings':
                    name=require(data,'event_name'); start=require(data,'start_at');end=require(data,'end_at')
                    sd=datetime.fromisoformat(start.replace('Z','+00:00'));ed=datetime.fromisoformat(end.replace('Z','+00:00'))
                    if sd.tzinfo is None or ed.tzinfo is None or ed<=sd:raise ValueError('Invalid event dates')
                    c.execute('UPDATE settings SET event_name=?,start_at=?,end_at=? WHERE id=1',(name,stamp(sd.astimezone(timezone.utc)),stamp(ed.astimezone(timezone.utc))))
                    return self.send(obj={'ok':True})
                if path=='/api/schedule':
                    title=require(data,'title');starts=require(data,'starts_at');location=require(data,'location')
                    dt=datetime.fromisoformat(starts.replace('Z','+00:00'))
                    if dt.tzinfo is None:raise ValueError('Timezone required')
                    c.execute('INSERT INTO schedule(title,starts_at,location,details) VALUES(?,?,?,?)',(title,stamp(dt.astimezone(timezone.utc)),location,str(data.get('details',''))[:500]))
                    return self.send(201,{'ok':True})
                return self.send(404,{'error':'Unknown endpoint'})
        except (ValueError,TypeError,sqlite3.IntegrityError,json.JSONDecodeError) as e:return self.send(400,{'error':str(e)})
        except Exception as e:
            print('Server error',repr(e));return self.send(500,{'error':'Server error'})

if __name__=='__main__':
    initialize();print(f'HackWave running at http://{HOST}:{PORT}',flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
