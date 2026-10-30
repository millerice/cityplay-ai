"use strict";
const CityPlayMap = (() => {
  let map, layer, markers=[], pendingFrame=null, needsFit=false;
  function schedule(update) {
    if (pendingFrame!==null) cancelAnimationFrame(pendingFrame);
    pendingFrame=requestAnimationFrame(()=>{pendingFrame=null;update();});
  }
  function updateSize() {
    if (Number.isFinite(map.getZoom())) map.stop();
    map.invalidateSize({pan:false});
  }
  function resize() {
    schedule(()=>{
      if (!map) return;
      const container=map.getContainer();
      if (!container.clientWidth || !container.clientHeight) return;
      updateSize();
      // A newly rendered result may have been hidden by the mobile list view.
      if (needsFit) {
        const points=markers.filter(Boolean).map(marker=>marker.getLatLng());
        if (points.length) map.fitBounds(L.latLngBounds(points),{padding:[45,45],maxZoom:15,animate:false});
        needsFit=false;
      }
    });
  }
  function focus(index) {
    if (!markers[index]) return;
    document.getElementById('map-panel').scrollIntoView({behavior:'smooth',block:'center'});
    needsFit=false;
    const marker=markers[index];
    schedule(()=>{updateSize();map.setView(marker.getLatLng(),16,{animate:false});marker.openPopup();});
  }
  function render(cards,area) {
    const panel=document.getElementById('map-panel');
    panel.hidden=!cards.length;
    if (pendingFrame!==null) {cancelAnimationFrame(pendingFrame);pendingFrame=null;}
    needsFit=false;
    if (!cards.length) {if(layer)layer.clearLayers();markers=[];return;}
    if (!window.L) {document.getElementById('map-status').textContent=t('map.loadFailed');return;}
    if (!map) {
      map=L.map('recommendation-map',{scrollWheelZoom:false});
      const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);
      tiles.on('tileerror',()=>{document.getElementById('map-status').textContent=t('map.tileError');});
      layer=L.layerGroup().addTo(map);
    }
    layer.clearLayers();markers=[];document.getElementById('map-status').textContent=t('map.status');
    cards.forEach((card,index)=>{
      const p=card.location;
      if(!p||!Number.isFinite(p.lat)||!Number.isFinite(p.lon)||Math.abs(p.lat)>90||Math.abs(p.lon)>180)return;
      const marker=L.marker([p.lat,p.lon],{icon:L.divIcon({className:'numbered-map-marker',html:String(index+1),iconSize:[30,30],iconAnchor:[15,15]})}).addTo(layer);
      const popup=document.createElement('div');const title=document.createElement('strong');title.textContent=`${index+1}. ${card.name}`;popup.append(title);
      const address=document.createElement('p');address.textContent=card.address;popup.append(address);
      const description=document.createElement('p');description.className='map-place-description';
      if(typeof card.description==='string'&&card.description.trim()) {
        description.textContent=card.description.trim();
        const source=document.createElement('small');source.textContent=t('map.introSource');popup.append(source,description);
      } else {
        const label=i18nLookup('cat.'+card.category);
        description.textContent=t('map.generic',{category:label!==null?label:t('cat.generic'),distance:Number.isFinite(card.straight_line_distance_m)?t('map.genericDistance',{km:(card.straight_line_distance_m/1000).toFixed(1)}):''});
        popup.append(description);
      }
      const button=document.createElement('button');button.textContent=t('map.viewCard');button.className='text-button';button.addEventListener('click',()=>{setResultView('list');document.getElementById(`place-card-${index}`)?.scrollIntoView({behavior:'smooth',block:'center'});});popup.append(document.createElement('br'),button);
      marker.bindPopup(popup);markers[index]=marker;
    });
    if(area&&Number.isFinite(area.lat)&&Number.isFinite(area.lon))L.circle([area.lat,area.lon],{radius:area.radius_m,color:'#213c36',fillOpacity:0.025,weight:1,dashArray:'5 5'}).bindTooltip(t('map.areaCircle')).addTo(layer);
    needsFit=true;resize();
  }
  return {render,focus,resize};
})();
