function openModal(id) {
  const d = document.getElementById(id);
  if (!d) return;
  d.querySelectorAll('input:not([type=hidden])').forEach(x => { if (x.type === 'datetime-local') x.value = ''; });
  if (id === 'flight-modal') {
    const now = new Date();
    const later = new Date(now.getTime()+3600000);
    const arrival = new Date(now.getTime()+10800000);
    document.getElementById('f-departure').value = localDate(later);
    document.getElementById('f-arrival').value = localDate(arrival);
  }
  d.showModal();
}
function closeModal(id) { document.getElementById(id)?.close(); }
function localDate(d) { const z=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}`; }
function editFlight(f) {
  openModal('flight-modal');
  document.getElementById('flight-title').textContent = 'Edit ' + f.flight_number;
  const fields = {id:f.id,number:f.flight_number,origin:f.origin,destination:f.destination,departure:localDate(new Date(f.departure_time)),arrival:localDate(new Date(f.arrival_time)),status:f.status,aircraft:f.aircraft_id||'',pilot:f.pilot_id||''};
  Object.entries(fields).forEach(([k,v])=>{ const el=document.getElementById('f-'+k); if(el) el.value=v; });
}
function editPilot(p) {
  openModal('pilot-modal'); document.getElementById('pilot-title').textContent='Edit pilot';
  const fields={id:p.id,code:p.pilot_code,rank:p.rank,name:p.name,license:p.license_number||'',hours:p.flight_hours};
  Object.entries(fields).forEach(([k,v])=>{const el=document.getElementById('p-'+k);if(el)el.value=v;});
}
function editAircraft(a) {
  openModal('aircraft-modal'); document.getElementById('aircraft-title').textContent='Edit aircraft';
  const fields={id:a.id,registration:a.registration,capacity:a.capacity,model:a.model,status:a.status};
  Object.entries(fields).forEach(([k,v])=>{const el=document.getElementById('a-'+k);if(el)el.value=v;});
}
document.addEventListener('click', e => { if(e.target.matches('dialog.modal')) e.target.close(); });
