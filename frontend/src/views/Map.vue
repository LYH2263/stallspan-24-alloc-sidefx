<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const mode = ref<'confirmed' | 'preview' | null>(null)
const vendors = ref<any[]>([])
const busy = ref(false)
const message = ref('')

async function loadLatestOrPreview() {
  // 只读最近一次确认；没有确认过则试摆，绝不隐式落库。
  try {
    data.value = await api('/allocate/latest?segment_id=1')
    mode.value = 'confirmed'
  } catch {
    data.value = await api('/allocate/preview?segment_id=1', { method: 'POST' })
    mode.value = 'preview'
  }
}

async function preview() {
  busy.value = true; message.value = ''
  try {
    // 试摆：运行表与审计表都不变，色块仅为预演。
    data.value = await api('/allocate/preview?segment_id=1', { method: 'POST' })
    mode.value = 'preview'
  } finally { busy.value = false }
}

async function confirm() {
  busy.value = true; message.value = ''
  try {
    // 确认：运行行与审计事件在同一事务落库后才刷新色块。
    data.value = await api('/allocate/confirm?segment_id=1', { method: 'POST' })
    mode.value = 'confirmed'
    message.value = `确认成功：运行 #${data.value.id} 已与审计事件同事务落库`
  } finally { busy.value = false }
}

async function resetToSeed() {
  busy.value = true; message.value = ''
  try {
    // 裁库：运行/审计/色块同步恢复；成功后用一次不落库的试摆重绘绿仓色块。
    await api('/admin/reset', { method: 'POST' })
    data.value = await api('/allocate/preview?segment_id=1', { method: 'POST' })
    mode.value = 'preview'
    message.value = '已裁回绿仓种子，色块同步恢复'
  } finally { busy.value = false }
}

onMounted(async () => {
  vendors.value = await api('/vendors')
  await loadLatestOrPreview()
})
const colors = ['#e8a87c','#85dcb8','#e27d60','#c38d9e','#41b3a3','#f4a261','#e76f51']
const cells = computed(() => {
  if (!data.value) return []
  const width = data.value.segment.width_m
  const out: any[] = []
  for (const p of data.value.pillars || []) {
    out.push({ type: 'pillar', start: p.position_m - p.thickness_m/2, w: p.thickness_m, label: p.label || '挡柱' })
  }
  for (const [i, p] of (data.value.placements || []).entries()) {
    out.push({ type: 'stall', start: p.start_m, w: p.width_m, label: p.vendor_name, color: colors[i % colors.length] })
  }
  return out.sort((a,b) => a.start - b.start).map(c => ({ ...c, pct: Math.max((c.w / width) * 100, 2) }))
})
const rejectedCount = computed(() => data.value?.rejected?.length || 0)
</script>
<template>
  <div class="ss-street-wrap">
    <h1>街段分配带</h1>
    <p class="sub">沿街一维开间 · 挡柱为竖直阻断 · 底部为摊主排队</p>
    <div class="ss-actions">
      <button class="btn" :disabled="busy" @click="preview">试摆预览（不落库）</button>
      <button class="btn btn-primary" :disabled="busy" @click="confirm">确认落库</button>
      <button class="btn btn-danger" :disabled="busy" @click="resetToSeed">裁回种子</button>
    </div>
    <p v-if="message" class="ss-hint">{{ message }}</p>
    <div class="ss-mode-tag" v-if="data">
      <span v-if="mode === 'confirmed'" class="tag tag-confirmed">
        已确认 · 运行 #{{ data.id }}（运行与审计同事务落库）
      </span>
      <span v-else class="tag tag-preview">试摆预览 · 未落库</span>
      <span v-if="rejectedCount" class="tag tag-rejected">
        {{ rejectedCount }} 个摊位放不下（仍为确认成功，不作拒绝处理）
      </span>
    </div>
    <div class="ss-band-ruler" v-if="data">
      <span>0 m</span>
      <span>{{ data.segment.name }} · {{ data.segment.width_m }} m</span>
      <span>{{ data.segment.width_m }} m</span>
    </div>
    <div class="ss-street-band" v-if="data">
      <div class="ss-street-inner">
        <div
          v-for="(c,i) in cells" :key="i"
          class="ss-band-cell"
          :class="{ 'ss-pillar': c.type === 'pillar' }"
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
    <div class="card" v-if="data">
      <table>
        <thead><tr><th>摊主</th><th>起点</th><th>终点</th><th>宽度</th></tr></thead>
        <tbody>
          <tr v-for="p in data.placements" :key="p.vendor_id">
            <td>{{ p.vendor_name }}</td><td>{{ p.start_m }}</td><td>{{ p.end_m }}</td><td>{{ p.width_m }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
