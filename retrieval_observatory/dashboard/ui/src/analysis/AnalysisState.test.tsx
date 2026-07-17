import { renderToStaticMarkup } from 'react-dom/server'
import { describe,expect,it } from 'vitest'
import AnalysisState from './AnalysisState'
import { AnalysisResult } from './contracts'
const base=(state:'ready'|'partial'|'unavailable'):AnalysisResult<{count:number}>=>({state,scope:{db_id:'main',service_id:null,run_id:'r',since:null,until:null,cohort_id:null},evidence:{evidence_class:state==='unavailable'?'unavailable':'measured',method_id:'test',method_version:'1',sample_size:state==='unavailable'?0:1,population_size:1,coverage:state==='partial'?.5:state==='ready'?1:0,thresholds:{},limitations:state==='partial'?['limited']:[],supporting_trace_ids:[],supporting_query_ids:[]},data:state==='unavailable'?null:{count:1},unavailable_reason:state==='unavailable'?'missing':null})
describe('AnalysisState',()=>{it.each(['ready','partial','unavailable'] as const)('renders %s',state=>expect(renderToStaticMarkup(<AnalysisState result={base(state)}>{data=><b>{data.count}</b>}</AnalysisState>)).toContain(`data-state="${state}"`))})
