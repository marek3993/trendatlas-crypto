import {CleanPerformance} from "@/components/clean-performance";
export const dynamic="force-dynamic";
export default async function Home({searchParams}:{searchParams:Promise<{lang?:string}>}) {
 const {lang}=await searchParams;
 return <main><CleanPerformance language={lang==="en"?"en":"sk"}/></main>;
}
