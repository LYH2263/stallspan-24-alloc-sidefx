<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const noConfirm = ref(false)
onMounted(async () => {
  try {
    const data = await api('/allocate/latest?segment_id=1')
    rows.value = data.rejected || []
  } catch {
    // 尚无确认记录：latest 只读不写，不隐式补运行行。
    noConfirm.value = true
  }
})
</script>
<template>
  <h1>放不下</h1>
  <p class="sub">无法在连续空档内安置且不跨越挡柱的摊位</p>
  <p v-if="noConfirm" class="muted">尚无确认记录，请先在「分配带」确认落库（试摆预览不计入）。</p>
  <div class="card" v-else>
    <table>
      <thead><tr><th>摊主</th><th>需求宽度</th><th>原因</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.vendor_id">
          <td>{{ r.vendor_name }}</td><td>{{ r.width_m }}</td><td>{{ r.reason }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">全部放下</p>
  </div>
</template>
