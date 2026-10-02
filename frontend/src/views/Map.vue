<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const SEGMENT_ID = 1
const confirmed = ref<any>(null) // 已确认落位：主图口径，来自运行表
const trial = ref<any>(null)     // 试摆预览：只算不落库
const segment = ref<any>(null)
const pillars = ref<any[]>([])
const vendors = ref<any[]>([])
async function refreshConfirmed() {
  try { confirmed.value = await api(`/allocate/latest?segment_id=${SEGMENT_ID}`) }
  catch { confirmed.value = null } // 尚无已确认落位：主图不留色块
}
async function runPreview() { trial.value = await api(`/allocate/preview?segment_id=${SEGMENT_ID}`, { method: 'POST' }) }
async function confirm() {
  confirmed.value = await api(`/allocate/confirm?segment_id=${SEGMENT_ID}`, { method: 'POST' })
  trial.value = null
}
onMounted(async () => {
  ;[vendors.value, pillars.value, segment.value] = await Promise.all([
    api('/vendors'),
    api('/pillars'),
    api('/segments').then((ss: any[]) => ss.find(s => s.id === SEGMENT_ID) || ss[0]),
  ])
  await refreshConfirmed()
})
const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const view = computed(() => confirmed.value || trial.value)
const isTrial = computed(() => !confirmed.value && !!trial.value)
const cells = computed(() => {
  const width = segment.value?.width_m
  if (!width) return []
  const out: any[] = []
  for (const p of view.value?.pillars || pillars.value) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const [i, p] of (view.value?.placements || []).entries()) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, color: colors[i % colors.length] })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队</p>
    <p>
      <span v-if="confirmed" class="ss-badge ss-badge-ok">已确认 · 运行 #{{ confirmed.id }}</span>
      <span v-else-if="isTrial" class="ss-badge ss-badge-trial">试摆预览 · 未确认不落库</span>
      <span v-else class="ss-badge">尚未确认落位</span>
    </p>
    <button class="btn" @click="runPreview">试摆预览</button>
    <button class="btn" @click="confirm">确认落位</button>
    <div class="ss-band-ruler" v-if="segment">
      <span>0 m</span>
      <span>{{ segment.name }} · {{ segment.width_m }} m</span>
      <span>{{ segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="segment">
      <div class="ss-street-inner">
        <div
          v-for="(c,i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar', 'ss-trial': isTrial && c.type === 'stall' }"
          :style="{ width: c.pct + '%', background: c.type === 'pillar' ? undefined : c.color, flex: '0 0 ' + c.pct + '%' }"
        >{{ c.label }}</div>
      </div>
    </div>
    <div class="ss-vendor-queue">
      <div v-for="v in vendors" :key="v.id" class="ss-vendor-chip">
        <strong>{{ v.name }}</strong>
        <span>需 {{ v.stall_width_m }} m · 优先 {{ v.priority }}</span>
      </div>
    </div>
    <div class="card" v-if="view">
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th></tr></thead>
        <tbody>
          <tr v-for="p in view.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
