import {readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import path from "node:path";
import {createAdminClient} from "@/lib/supabase/admin";
import {parseCleanPublic} from "@/lib/clean-public";
async function main() {
 const dir=process.env.TRENDATLAS_CLEAN_STATE_DIR;if(!dir)throw new Error("publication path missing");
 const names=["clean5050_metrics.json","clean5050_timeseries.csv","signal.json"];
 const texts=await Promise.all(names.map(n=>readFile(path.join(dir,n),"utf8")));
 const data=parseCleanPublic(texts[0],texts[1],texts[2]);if(data.stale)throw new Error("stale publication");
 const version=createHash("sha256").update(texts.join("\0")).digest("hex"),db=createAdminClient();
 const bucket="trendatlas-clean-public";
 const existing=await db.storage.getBucket(bucket);
 if(existing.error) {const r=await db.storage.createBucket(bucket,{public:true,allowedMimeTypes:["application/json","text/csv"],fileSizeLimit:5000000});if(r.error)throw new Error("public bucket unavailable");}
 else if(!existing.data.public)throw new Error("public bucket configuration differs");
 for(let i=0;i<names.length;i++) {
  const r=await db.storage.from(bucket).upload(`${version}/${names[i]}`,texts[i],{contentType:i===1?"text/csv":"application/json",upsert:true,cacheControl:"3600"});if(r.error)throw new Error("publication failed");
 }
 const r=await db.storage.from(bucket).upload("latest.json",JSON.stringify({version,closed_day:data.signal.decision_closed_day_utc}),{contentType:"application/json",upsert:true,cacheControl:"0"});if(r.error)throw new Error("publication pointer failed");
 console.log(JSON.stringify({status:"CLEAN_PUBLIC_ARTIFACTS_PUBLISHED",version}));
}
main().catch(()=>{console.error("Clean publication failed safely.");process.exitCode=1;});
