import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import { DbSource, fetchDbs } from '../api'
import { DashboardSelection, parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'
export { parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'
export type { DashboardSelection } from './dashboardQuery'

const Context=createContext<{selection:DashboardSelection;databases:DbSource[];updateSelection:(p:Partial<DashboardSelection>,m?:'push'|'replace')=>void}|null>(null)
function query(){return window.location.hash.split('?')[1]||''}
export function DashboardProvider({children}:{children:ReactNode}){const [selection,setSelection]=useState(()=>parseDashboardQuery(query()));const [databases,setDatabases]=useState<DbSource[]>([]);useEffect(()=>{fetchDbs().then(d=>{setDatabases(d);setSelection(s=>({...s,db:d.some(x=>x.db_id===s.db)?s.db:d[0]?.db_id||null}))}).catch(()=>setDatabases([]))},[]);useEffect(()=>{const h=()=>setSelection(prev=>parseDashboardQuery(query(),prev));window.addEventListener('hashchange',h);return()=>window.removeEventListener('hashchange',h)},[]);const value=useMemo(()=>({selection,databases,updateSelection:(p:Partial<DashboardSelection>,mode: 'push'|'replace'='push')=>{const n={...selection,...p};setSelection(n);const path=window.location.hash.split('?')[0]||'#/';history[mode==='replace'?'replaceState':'pushState'](null,'',`${path}?${serializeDashboardQuery(n)}`);window.dispatchEvent(new HashChangeEvent('hashchange'))}}),[selection,databases]);return <Context.Provider value={value}>{children}</Context.Provider>}
export function useDashboardContext(){const v=useContext(Context);if(!v)throw new Error('DashboardProvider required');return v}
