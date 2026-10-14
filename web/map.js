"use strict";
const CityPlayMap = (() => {
  let map, layer, markers=[];
  function focus(index) {
    if (!markers[index]) return;
    document.getElementById('map-panel').scrollIntoView({behavior:'smooth',block:'center'});
    map.invalidateSize();map.setView(markers[index].getLatLng(),16);markers[index].openPopup();
  }
  function render(cards,area) {
    const panel=document.getElementById('map-panel');
    panel.hidden=!cards.length;
    if (!cards.length) {if(layer)layer.clearLayers();markers=[];return;}
    if (!window.L) {document.getElementById('map-status').textContent='地图组件加载失败；推荐卡片仍可使用。';return;}
    if (!map) {
      map=L.map('recommendation-map',{scrollWheelZoom:false});
      const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);
      tiles.on('tileerror',()=>{document.getElementById('map-status').textContent='底图加载不完整；标记使用 Qloo 原始坐标。请检查网络后重试。';});
      layer=L.layerGroup().addTo(map);
    }
    layer.clearLayers();markers=[];document.getElementById('map-status').textContent='底图：OpenStreetMap · 可缩放、拖动；首次加载需联网。';
    const points=[];
    cards.forEach((card,index)=>{
      const p=card.location;
      if(!p||!Number.isFinite(p.lat)||!Number.isFinite(p.lon)||Math.abs(p.lat)>90||Math.abs(p.lon)>180)return;
      const marker=L.marker([p.lat,p.lon],{icon:L.divIcon({className:'numbered-map-marker',html:String(index+1),iconSize:[30,30],iconAnchor:[15,15]})}).addTo(layer);
      const popup=document.createElement('div');const title=document.createElement('strong');title.textContent=`${index+1}. ${card.name}`;popup.append(title);
      const address=document.createElement('p');address.textContent=card.address;popup.append(address);
      const coordinates=document.createElement('small');coordinates.textContent=`纬度 ${p.lat} · 经度 ${p.lon}`;popup.append(coordinates);
      const button=document.createElement('button');button.textContent='查看对应推荐';button.className='text-button';button.addEventListener('click',()=>document.getElementById(`place-card-${index}`)?.scrollIntoView({behavior:'smooth',block:'center'}));popup.append(document.createElement('br'),button);
      marker.bindPopup(popup);markers[index]=marker;points.push([p.lat,p.lon]);
    });
    if(area&&Number.isFinite(area.lat)&&Number.isFinite(area.lon))L.circle([area.lat,area.lon],{radius:area.radius_m,color:'#213c36',fillOpacity:0.025,weight:1,dashArray:'5 5'}).bindTooltip('所选探索中心与半径').addTo(layer);
    requestAnimationFrame(()=>{map.invalidateSize();if(points.length)map.fitBounds(L.latLngBounds(points),{padding:[45,45],maxZoom:15});});
  }
  return {render,focus};
})();
