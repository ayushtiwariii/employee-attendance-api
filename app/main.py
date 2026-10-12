"""HROne Employee Attendance & Analytics API (contract v2.0)."""

import os, re, calendar

from datetime import datetime, date, time, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from contextlib import asynccontextmanager

from typing import Optional, Literal

from zoneinfo import ZoneInfo



from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query, Path, Body

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator



load_dotenv(override=False)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

client = db = None

try:

    from pymongo import MongoClient, ASCENDING, DESCENDING

    from pymongo.errors import PyMongoError, DuplicateKeyError, OperationFailure

except ImportError:

    MongoClient = None

    ASCENDING, DESCENDING = 1, -1

    PyMongoError = Exception

    DuplicateKeyError = type("DuplicateKeyError", (Exception,), {})

    OperationFailure = Exception



IST = ZoneInfo("Asia/Kolkata")

PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}

STATUSES = PRESENCE | {"ABSENT", "LEAVE"}



# ---------- validation models ----------

def valid_date(v):

    try: return date.fromisoformat(v).isoformat() == v

    except Exception: return False



def valid_month(v): return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v or ""))



def epoch_ms(v):

    if v is None: return None

    if isinstance(v, bool) or not isinstance(v, int) or not 100_000_000_000 <= v <= 4_102_444_800_000:

        raise ValueError("must be an epoch-millisecond integer")

    return v



class EmployeeCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")

    name: str = Field(min_length=1, max_length=100)

    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    department: str = Field(min_length=1, max_length=50)

    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    joined_on: str

    @field_validator("joined_on")

    @classmethod

    def check_joined(cls, v):

        if not valid_date(v): raise ValueError("joined_on must be YYYY-MM-DD")

        return v

    @model_validator(mode="after")

    def shifts_differ(self):

        if self.shift_start == self.shift_end: raise ValueError("shift_start must differ from shift_end")

        return self



class PunchInRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str

    punched_at: Optional[int] = None

    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

    @field_validator("punched_at", mode="before")

    @classmethod

    def check_time(cls,v): return epoch_ms(v)



class PunchOutRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str

    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")

    @classmethod

    def check_time(cls,v): return epoch_ms(v)



class RegularizeRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None

    punch_in: Optional[int] = None

    punch_out: Optional[int] = None

    reason: str = Field(min_length=5, max_length=200)

    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("punch_in", "punch_out", mode="before")

    @classmethod

    def check_time(cls,v): return epoch_ms(v)



@asynccontextmanager

async def lifespan(app: FastAPI):

    global client, db

    if MongoClient:

        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000, tz_aware=True)

        db = client[MONGO_DB]

        try:

            client.admin.command("ping")

            db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")

            db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="department_joined")
            db.employees.create_index([("joined_on", ASCENDING)], name="employee_joined")

            db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")

            db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_emp")

            db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING), ("status", ASCENDING)], name="attendance_employee_date_status")

            db.attendance_logs.create_index([("date", ASCENDING), ("late_minutes", DESCENDING)], name="attendance_date_late")

        except PyMongoError:

            # The process may start while MongoDB is still coming up; /health stays 503 until reachable.

            pass

    try: yield

    finally:

        if client is not None: client.close()

        client = db = None



app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)



def require_db():

    if client is None or db is None: raise HTTPException(503, "MongoDB is unavailable")

    try: client.admin.command("ping")

    except Exception: raise HTTPException(503, "MongoDB is unavailable")

    return db



def as_utc_dt(ms):

    ms = epoch_ms(ms)

    return datetime.fromtimestamp(ms // 1000, timezone.utc).replace(microsecond=0)



def dt_ms(value):
    if value is None:
        return None

    # MongoDB/BSON timestamps may already be integers
    if isinstance(value, (int, float)):
        return int(value)

    # Handle NumPy/Pandas integer types such as Int64
    if hasattr(value, "item"):
        value = value.item()
        if isinstance(value, (int, float)):
            return int(value)

    # Handle datetime values
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return int(value.timestamp() * 1000)




def trunc_ms(ms): return (epoch_ms(ms) // 1000) * 1000



def ist_dt(ms): return as_utc_dt(ms).astimezone(IST)





def shift_bounds(emp, punch_ms):



    local = ist_dt(punch_ms)



    start_t = time.fromisoformat(emp.get("shift_start", "09:30"))

    end_t = time.fromisoformat(emp.get("shift_end", "18:30"))



    shift_day = local.date()



    if end_t <= start_t and local.time().replace(tzinfo=None) < end_t:

        shift_day -= timedelta(days=1)



    start = datetime.combine(shift_day, start_t, IST)

    end_day = shift_day + (

        timedelta(days=1) if end_t <= start_t else timedelta()

    )

    end = datetime.combine(end_day, end_t, IST)



    return start, end, shift_day.isoformat()





def compute_late_minutes(emp, punch_ms):

    start, _, _ = shift_bounds(emp, punch_ms)

    punch = ist_dt(punch_ms)

    seconds = int((punch - start).total_seconds())

    return seconds // 60 if seconds > 600 else 0



def compute_work_hours(punch_in, punch_out):

    if punch_in is None or punch_out is None: return None

    hours = Decimal(str((punch_out - punch_in) / 1000 / 3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return float(hours)



def compute_overtime(emp, punch_out_ms, punch_in_ms):

    _, shift_end, _ = shift_bounds(emp, punch_in_ms)

    mins = int((ist_dt(punch_out_ms) - shift_end).total_seconds() // 60)

    return mins if mins >= 30 else 0



def _as_epoch_ms(value):
    """Normalize a MongoDB datetime or epoch-millisecond integer to milliseconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return dt_ms(value)
    return epoch_ms(value)


def calc_fields(emp, record):
    """Calculate derived attendance fields from BSON datetimes or epoch milliseconds."""
    # MongoClient is configured with tz_aware=True, so MongoDB date fields are
    # returned as datetime objects. The calculation helpers expect epoch ms.
    pi = _as_epoch_ms(record.get("punch_in"))
    po = _as_epoch_ms(record.get("punch_out"))

    if record.get("status") not in PRESENCE:
        return {
            "late_minutes": 0,
            "work_hours": None,
            "overtime_minutes": 0,
            "half_day": False,
        }

    late = compute_late_minutes(emp, pi) if pi is not None else 0
    work_hours = compute_work_hours(pi, po)
    overtime = compute_overtime(emp, po, pi) if po is not None and pi is not None else 0

    return {
        "late_minutes": late,
        "work_hours": work_hours,
        "overtime_minutes": overtime,
        "half_day": bool(work_hours is not None and work_hours < 4.5),
    }


def serialize_employee(d):

    return {k: (dt_ms(v) if k == "created_at" else v) for k,v in d.items() if k != "_id"}



def serialize_record(d):

    out = {k:v for k,v in d.items() if k != "_id"}

    for k in ("punch_in", "punch_out"):

        out[k] = dt_ms(out.get(k))

    hist=[]

    for h in out.get("history", []) or []:

        x=dict(h); x["at"]=dt_ms(x.get("at")); changes={}

        for field, pair in (x.get("changes") or {}).items():

            changes[field] = dict(pair)

            if field in ("punch_in", "punch_out"):

                changes[field]["from"] = dt_ms(pair.get("from")); changes[field]["to"] = dt_ms(pair.get("to"))

        x["changes"]=changes; hist.append(x)

    out["history"]=hist

    out.setdefault("history", []); out.setdefault("half_day", False)

    return out



def month_range(month):

    if not valid_month(month): raise HTTPException(422, "month must be YYYY-MM")

    y,m=map(int,month.split("-")); start=date(y,m,1); end=date(y,m,calendar.monthrange(y,m)[1])

    return start.isoformat(), end.isoformat()



def working_days(joined_on, start_s, end_s):

    start=max(date.fromisoformat(joined_on),date.fromisoformat(start_s)); end=date.fromisoformat(end_s)

    if start>end:return 0

    return sum(1 for i in range((end-start).days+1) if (start+timedelta(days=i)).weekday()<5)



def qround(value, places=2):

    if value is None:return None

    return float(Decimal(str(value)).quantize(Decimal("1."+"0"*places), rounding=ROUND_HALF_UP))



def parse_range(v, label):

    if not valid_date(v): raise HTTPException(422, f"{label} must be YYYY-MM-DD")

    return date.fromisoformat(v)



@app.get("/health")

def health():

    require_db(); return {"status":"ok"}



@app.post("/employees", status_code=201)

def create_employee(payload: EmployeeCreate):

    d=require_db(); doc=payload.model_dump(); doc["created_at"]=datetime.now(timezone.utc).replace(microsecond=0)

    try: d.employees.insert_one(doc)

    except DuplicateKeyError: raise HTTPException(409,"Employee code already exists")

    except PyMongoError: raise HTTPException(503,"Database operation failed")

    return serialize_employee(doc)



@app.get("/employees")

def list_employees(department: Optional[str]=None, page: int=Query(1,ge=1), page_size: int=Query(20,ge=1,le=100)):

    d=require_db(); filt={}

    if department is not None:filt["department"]=department

    total=d.employees.count_documents(filt)

    cur=d.employees.find(filt, {"_id":0}).sort("emp_code",ASCENDING).skip((page-1)*page_size).limit(page_size)

    return {"items":[serialize_employee(x) for x in cur],"total":total,"page":page,"page_size":page_size}



@app.post("/attendance/punch-in", status_code=201)

def punch_in(payload: PunchInRequest):

    d=require_db(); emp=d.employees.find_one({"emp_code":payload.emp_code})

    if not emp: raise HTTPException(404,"Unknown employee")

    ms=trunc_ms(payload.punched_at if payload.punched_at is not None else int(datetime.now(timezone.utc).timestamp()*1000))

    _,_,day=shift_bounds(emp,ms)

    if day < emp["joined_on"]: raise HTTPException(422,"Punch-in is before employee joining date")

    doc={"emp_code":payload.emp_code,"date":day,"status":payload.status,"punch_in":as_utc_dt(ms),"punch_out":None,"work_hours":None,"late_minutes":compute_late_minutes(emp,ms),"overtime_minutes":0,"half_day":False,"history":[]}

    try:d.attendance_logs.insert_one(doc)

    except DuplicateKeyError:raise HTTPException(409,"Already punched in for this date")

    except PyMongoError:raise HTTPException(503,"Database operation failed")

    return serialize_record(doc)



@app.post("/attendance/punch-out")

def punch_out(payload: PunchOutRequest):

    d=require_db(); emp=d.employees.find_one({"emp_code":payload.emp_code})

    if not emp:raise HTTPException(404,"Unknown employee")

    ms=trunc_ms(payload.punched_at if payload.punched_at is not None else int(datetime.now(timezone.utc).timestamp()*1000)); po=as_utc_dt(ms)

    rec=d.attendance_logs.find_one({"emp_code":payload.emp_code,"punch_in":{"$lte":po}},sort=[("punch_in",DESCENDING)])

    if not rec:raise HTTPException(404,"No punch-in found")

    if rec.get("punch_out") is not None:raise HTTPException(409,"Already punched out")

    pi=dt_ms(rec["punch_in"])

    if ms<=pi or ms-pi>24*3600*1000:raise HTTPException(422,"punch-out must be after punch-in and within 24 hours")

    fields=calc_fields(emp,{**rec,"punch_out":po})

    # Guard every input used to calculate derived values. A simultaneous regularization
    # may change punch_in/status while leaving punch_out null; that must not be overwritten.
    result=d.attendance_logs.update_one(
        {"emp_code":payload.emp_code,"date":rec["date"],"punch_out":None,
         "punch_in":rec.get("punch_in"),"status":rec.get("status")},
        {"$set":{"punch_out":po,**fields}}
    )

    if result.modified_count!=1:raise HTTPException(409,"Already punched out")

    updated=d.attendance_logs.find_one({"emp_code":payload.emp_code,"date":rec["date"]})

    return serialize_record(updated)



@app.get("/attendance")

def list_attendance(emp_code:Optional[str]=None,date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):

    d=require_db(); filt={}

    if emp_code is not None:filt["emp_code"]=emp_code

    if status is not None:

        if status not in STATUSES:raise HTTPException(422,"Invalid status")

        filt["status"]=status

    if date_from:

        parse_range(date_from,"date_from");filt.setdefault("date",{})["$gte"]=date_from

    if date_to:

        parse_range(date_to,"date_to");filt.setdefault("date",{})["$lte"]=date_to

    if date_from and date_to and date_from>date_to:raise HTTPException(422,"date_from must be <= date_to")

    total=d.attendance_logs.count_documents(filt)

    cur=d.attendance_logs.find(filt).sort([("date",DESCENDING),("emp_code",ASCENDING)]).skip((page-1)*page_size).limit(page_size)

    return {"items":[serialize_record(x) for x in cur],"total":total,"page":page,"page_size":page_size}



@app.patch("/attendance/{emp_code}/{date}")

def regularize(emp_code:str,date:str,payload:RegularizeRequest):

    d=require_db(); day=parse_range(date,"date"); emp=d.employees.find_one({"emp_code":emp_code})

    if not emp:raise HTTPException(404,"Unknown employee")

    old=d.attendance_logs.find_one({"emp_code":emp_code,"date":date})

    if not old:raise HTTPException(404,"Attendance record not found")

    data=payload.model_dump(exclude={"reason","regularized_by"},exclude_unset=True)

    new={**old}; new.pop("_id",None)

    for k,v in data.items():

        if k in ("punch_in","punch_out"):new[k]=as_utc_dt(trunc_ms(v)) if v is not None else None

        else:new[k]=v

    if new["status"] in {"ABSENT","LEAVE"}:

        if "punch_in" in data or "punch_out" in data:raise HTTPException(422,"ABSENT/LEAVE cannot include punch_in or punch_out")

        new["punch_in"]=new["punch_out"]=None

    elif new.get("punch_in") is None:raise HTTPException(422,"Presence status requires punch_in")

    if new.get("punch_in") is not None:

        if ist_dt(dt_ms(new["punch_in"])).date().isoformat()!=date:raise HTTPException(422,"punch_in must be on attendance date in IST")

    if new.get("punch_out") is not None:

        if new.get("punch_in") is None or dt_ms(new["punch_out"])<=dt_ms(new["punch_in"]) or dt_ms(new["punch_out"])-dt_ms(new["punch_in"])>86400000:raise HTTPException(422,"Invalid punch_out")

    new.update(calc_fields(emp,new))

    changed={}

    for k in ["status","punch_in","punch_out","work_hours","late_minutes","overtime_minutes","half_day"]:

        a,b=old.get(k),new.get(k)

        if isinstance(a,datetime):a=dt_ms(a)

        if isinstance(b,datetime):b=dt_ms(b)

        if a!=b:changed[k]={"from":a,"to":b}

    if not changed:raise HTTPException(422,"Request does not change the record")

    hist={"at":datetime.now(timezone.utc).replace(microsecond=0),"by":payload.regularized_by,"reason":payload.reason,"changes":changed}

    # Optimistic concurrency: compare old fields and atomically append history.

    filt={"emp_code":emp_code,"date":date,"status":old.get("status"),"punch_in":old.get("punch_in"),"punch_out":old.get("punch_out")}
    # Legacy records may omit history entirely. Matching history=[] would never match
    # a missing field, so use an explicit existence predicate for that case.
    if "history" in old:
        filt["history"]=old["history"]
    else:
        filt["history"]={"$exists":False}

    update={k:new[k] for k in ["status","punch_in","punch_out","work_hours","late_minutes","overtime_minutes","half_day"]}

    result=d.attendance_logs.update_one(filt,{"$set":update,"$push":{"history":hist}})

    if result.modified_count!=1:raise HTTPException(409,"Record changed concurrently; retry")

    return serialize_record(d.attendance_logs.find_one({"emp_code":emp_code,"date":date}))





# Shared aggregation builders keep the production query and explain query identical.
def build_employee_monthly_pipeline(emp_code, start, end):
    return [
        {"$match": {"emp_code": emp_code, "date": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [
                {"$in": ["$status", list(PRESENCE)]},
                {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2, 3, 4, 5, 6]]}
            ]}, {"$cond": ["$half_day", 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": "$late_minutes"},
            "total_overtime_minutes": {"$sum": "$overtime_minutes"}
        }}
    ]


def build_department_summary_pipeline(start, end, department=None):
    match = {"joined_on": {"$lte": end}}
    if department is not None:
        match["department"] = department
    return [
        {"$match": match},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
            {"$match": {"$expr": {"$and": [
                {"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", start]}, {"$lte": ["$date", end]}
            ]}}}
        ], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$and": [
                {"$in": ["$logs.status", list(PRESENCE)]},
                {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": {"$ifNull": ["$logs.date", start]}}}}, [2, 3, 4, 5, 6]]}
            ]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}},
            "hours": {"$push": {"$cond": [{"$and": [
                {"$in": ["$logs.status", list(PRESENCE)]}, {"$ne": ["$logs.work_hours", None]}
            ]}, "$logs.work_hours", None]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$logs.late_minutes", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}
        }},
        {"$project": {"_id": 0, "department": "$_id", "headcount": {"$size": "$headcount"},
            "present_days": 1, "avg_work_hours": {"$avg": {"$filter": {"input": "$hours", "as": "h", "cond": {"$ne": ["$h", None]}}}},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1}},
        {"$match": {"headcount": {"$gt": 0}}},
        {"$sort": {"department": 1}}
    ]


def build_late_leaderboard_pipeline(start, end, department=None, limit=10):
    pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"}
    ]
    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "late_count": 1}}
    ]
    return pipeline


def build_department_trend_pipeline(department, from_, to, start, end):
    # Generate one row per requested date inside MongoDB, starting from a known
    # department employee. This also works when the department has zero logs.
    days = (end - start).days + 1
    start_dt = datetime.combine(start, time.min, timezone.utc)
    return [
        {"$match": {"department": department}},
        {"$limit": 1},
        {"$project": {"_id": 0, "department": 1}},
        {"$addFields": {"_day_offsets": {"$range": [0, days]}, "_range_start": start_dt}},
        {"$unwind": "$_day_offsets"},
        {"$addFields": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$dateAdd": {"startDate": "$_range_start", "unit": "day", "amount": "$_day_offsets"}}}}}},
        {"$lookup": {"from": "attendance_logs", "let": {"day": "$date", "dept": "$department"}, "pipeline": [
            {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
            {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
            {"$unwind": "$employee"},
            {"$match": {"$expr": {"$eq": ["$employee.department", "$$dept"]}}},
            {"$group": {"_id": None,
                "present_count": {"$sum": {"$cond": [{"$in": ["$status", list(PRESENCE)]}, {"$cond": ["$half_day", 0.5, 1]}, 0]}},
                "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}}
            }}
        ], "as": "stats"}},
        {"$lookup": {"from": "employees", "let": {"day": "$date", "dept": "$department"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$department", "$$dept"]}, {"$lte": ["$joined_on", "$$day"]}]}}},
            {"$count": "n"}
        ], "as": "hc"}},
        {"$addFields": {
            "headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.n", 0]}, 0]},
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$stats.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$stats.late_count", 0]}, 0]},
            "is_working_day": {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2, 3, 4, 5, 6]]}
        }},
        {"$addFields": {"attendance_rate": {"$cond": [{"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]}, {"$divide": ["$present_count", "$headcount"]}, None]}}},
        {"$setWindowFields": {"sortBy": {"date": 1}, "output": {"_avg": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": "$_avg"}},
        {"$sort": {"date": 1}}
    ]


@app.get("/analytics/employees/{emp_code}/monthly")

def employee_monthly(emp_code:str,month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):

    d=require_db(); emp=d.employees.find_one({"emp_code":emp_code})

    if not emp:raise HTTPException(404,"Unknown employee")

    start,end=month_range(month); work=working_days(emp["joined_on"],start,end)

    pipeline=build_employee_monthly_pipeline(emp_code,start,end)

    r=list(d.attendance_logs.aggregate(pipeline)); x=r[0] if r else {}

    return {"emp_code":emp_code,"month":month,"working_days":work,"present_days":qround(x.get("present_days",0)),"leave_days":x.get("leave_days",0),"late_count":x.get("late_count",0),"total_late_minutes":x.get("total_late_minutes",0),"total_overtime_minutes":x.get("total_overtime_minutes",0),"attendance_pct":qround(x.get("present_days",0)/work*100,2) if work else None}



@app.get("/analytics/departments/summary")

def department_summary(month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),department:Optional[str]=None):

    d=require_db(); start,end=month_range(month); match={"joined_on":{"$lte":end}}

    if department is not None:match["department"]=department

    pipeline=build_department_summary_pipeline(start,end,department)

    items=list(d.employees.aggregate(pipeline, allowDiskUse=True))

    for x in items:

        x["present_days"]=qround(x.get("present_days",0)); x["avg_work_hours"]=qround(x.get("avg_work_hours"))

    return {"month":month,"items":items}



@app.get("/analytics/leaderboard/late")

def late_leaderboard(month:str=Query(...,pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),limit:int=Query(10,ge=1,le=50),department:Optional[str]=None):

    d=require_db(); start,end=month_range(month)

    pipeline=build_late_leaderboard_pipeline(start,end,department,limit)

    try:items=list(d.attendance_logs.aggregate(pipeline,allowDiskUse=True))

    except OperationFailure as e:raise HTTPException(503,"MongoDB 5.0+ is required for ranking analytics") from e

    return {"month":month,"items":items}



@app.get("/analytics/departments/{department}/trend")

def department_trend(department:str,from_:str=Query(...,alias="from"),to:str=Query(...)):

    d=require_db(); start=parse_range(from_,"from"); end=parse_range(to,"to")

    if end<start or (end-start).days+1>92:raise HTTPException(422,"Invalid date range; maximum is 92 days")

    if d.employees.count_documents({"department":department})==0:raise HTTPException(404,"Unknown department")

    pipeline=build_department_trend_pipeline(department,from_,to,start,end)

    try:items=list(d.employees.aggregate(pipeline,allowDiskUse=True))

    except OperationFailure as e:raise HTTPException(503,"MongoDB 5.0+ is required for trend analytics") from e

    for x in items:

        x["present_count"]=qround(x.get("present_count",0)); x["attendance_rate"]=qround(x.get("attendance_rate"),4); x["moving_avg_7d"]=qround(x.get("moving_avg_7d"),4)


    return {"department":department,"items":items}



# Explain helpers use the same filters/sort/pagination and the same aggregate pipeline patterns.

def attendance_filter(emp_code,date_from,date_to,status):

    f={}

    if emp_code is not None:f["emp_code"]=emp_code

    if date_from:f.setdefault("date",{})["$gte"]=date_from

    if date_to:f.setdefault("date",{})["$lte"]=date_to

    if status:f["status"]=status

    return f



@app.get("/admin/explain/{endpoint}")

def explain(endpoint:str,emp_code:Optional[str]=None,month:Optional[str]=None,department:Optional[str]=None,limit:int=Query(10,ge=1,le=50),date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,from_:Optional[str]=Query(None,alias="from"),to:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):

    d=require_db(); allowed={"attendance_list","employee_monthly","department_summary","late_leaderboard","department_trend"}

    if endpoint not in allowed:raise HTTPException(422,"Unknown endpoint")

    if endpoint=="attendance_list":

        for v,n in [(date_from,"date_from"),(date_to,"date_to")]:

            if v:parse_range(v,n)

        if date_from and date_to and date_from>date_to:raise HTTPException(422,"Invalid date range")

        if status is not None and status not in STATUSES:raise HTTPException(422,"Invalid status")

        filt=attendance_filter(emp_code,date_from,date_to,status)

        cur=d.attendance_logs.find(filt).sort([("date",DESCENDING),("emp_code",ASCENDING)]).skip((page-1)*page_size).limit(page_size)

        exp=cur.explain("executionStats"); coll="attendance_logs"

    else:

        if not month or not valid_month(month):

            if endpoint!="department_trend":raise HTTPException(422,"month is required in YYYY-MM format")

        if endpoint=="employee_monthly":

            if not emp_code:raise HTTPException(422,"emp_code is required")

            start,end=month_range(month)

            pipeline=build_employee_monthly_pipeline(emp_code,start,end)

            exp=d.command("explain",{"aggregate":"attendance_logs","pipeline":pipeline,"cursor":{}},verbosity="executionStats");coll="attendance_logs"

        elif endpoint=="department_summary":

            start,end=month_range(month); f={"joined_on":{"$lte":end}}

            if department:f["department"]=department

            pipeline=build_department_summary_pipeline(start,end,department)
            exp=d.command("explain",{"aggregate":"employees","pipeline":pipeline,"cursor":{}},verbosity="executionStats");coll="employees"

        elif endpoint=="late_leaderboard":

            start,end=month_range(month); pipe=build_late_leaderboard_pipeline(start,end,department,limit)

            exp=d.command("explain",{"aggregate":"attendance_logs","pipeline":pipe,"cursor":{}},verbosity="executionStats");coll="attendance_logs"

        else:

            if not department or not from_ or not to:raise HTTPException(422,"department, from and to are required")

            a=parse_range(from_,"from");b=parse_range(to,"to")

            if b<a or (b-a).days+1>92:raise HTTPException(422,"Invalid date range")

            pipeline=build_department_trend_pipeline(department,from_,to,a,b)
            exp=d.command("explain",{"aggregate":"employees","pipeline":pipeline,"cursor":{}},verbosity="executionStats");coll="employees"

    return {"endpoint":endpoint,"collection":coll,"explain":exp}
