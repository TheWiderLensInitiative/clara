package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.PurchaseView
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.components.ProductPhoto
import info.thewiderlens.clara.ui.theme.ClaraColors

/** Purchases: every order Clara placed, saved as a playbook. Buy again repeats it fast (you still approve the price
 *  in Clara and in Link); long-press or Delete removes it. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PurchasesPage(
    state: UiState, onRefresh: () -> Unit, onDelete: (String) -> Unit, onBuyAgain: (PurchaseView) -> Unit,
    loadImage: suspend (String) -> ByteArray?, onBack: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    var open by remember { mutableStateOf<String?>(null) }
    var deleting by remember { mutableStateOf<PurchaseView?>(null) }
    var confirming by remember { mutableStateOf<PurchaseView?>(null) }
    val fmt = remember { java.text.SimpleDateFormat("MMM d, yyyy", java.util.Locale.getDefault()) }
    PageScaffold("Purchases", onBack) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            Text("Orders Clara placed. Each one keeps the exact steps she took, so Buy again skips the searching. " +
                "You still approve the price in Clara and in Link every time, and each order gets a new one-time card.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
            Spacer(Modifier.height(10.dp))
            val list = state.purchases
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                when {
                    list == null -> item { Text("Loading…", color = ClaraColors.Muted) }
                    list.isEmpty() -> item { Text("Nothing yet. When Clara buys something for you, it shows up here.", color = ClaraColors.Muted) }
                }
                items(list.orEmpty(), key = { it.id }) { p ->
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel)
                            .border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp))
                            .combinedClickable(onClick = { open = if (open == p.id) null else p.id }, onLongClick = { deleting = p })
                            .padding(12.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            ProductPhoto(p.image, loadImage, Modifier.size(64.dp).clip(RoundedCornerShape(10.dp)))
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(p.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(p.store, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted, maxLines = 1)
                                Text(
                                    p.total + (if (p.shipping.isNotBlank()) " (incl. ${p.shipping} shipping)" else "") +
                                        " · " + fmt.format(java.util.Date((p.at * 1000).toLong())) +
                                        (if (p.times > 1) " · bought ${p.times}×" else ""),
                                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan,
                                )
                            }
                        }
                        if (open == p.id) {
                            Spacer(Modifier.height(8.dp))
                            if (p.order.isNotBlank()) Text("Order #${p.order}", style = MaterialTheme.typography.bodySmall)
                            if (p.ship_to.isNotBlank()) Text("Shipped to ${p.ship_to}", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
                            if (p.steps.isNotEmpty()) {
                                Spacer(Modifier.height(6.dp))
                                Text("Playbook", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                                p.steps.forEachIndexed { i, s ->
                                    Text("${i + 1}. $s", style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.padding(vertical = 2.dp))
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (p.can_repeat) GradientButton("Buy again", modifier = Modifier.weight(1f)) { confirming = p }
                            else Text("Can't repeat automatically (not from a Shopify store)", style = MaterialTheme.typography.labelSmall,
                                color = ClaraColors.Muted, modifier = Modifier.weight(1f))
                            TextButton(onClick = { deleting = p }) { Text("Delete", color = ClaraColors.Danger) }
                        }
                    }
                }
            }
        }
    }
    confirming?.let { p ->
        AlertDialog(
            onDismissRequest = { confirming = null }, containerColor = ClaraColors.Panel,
            title = { Text("Buy again?") },
            text = { Text("Clara repeats this order: ${p.title}, shipped to ${p.ship_to.ifBlank { "your saved address" }}. " +
                "Last time it was ${p.total}. She shows you the new total to approve before anything is charged.") },
            confirmButton = { TextButton(onClick = { onBuyAgain(p); confirming = null }) { Text("Buy again", color = ClaraColors.Cyan) } },
            dismissButton = { TextButton(onClick = { confirming = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
    deleting?.let { p ->
        AlertDialog(
            onDismissRequest = { deleting = null }, containerColor = ClaraColors.Panel,
            title = { Text("Delete “${p.title.take(40)}”?") },
            text = { Text("It's removed from Purchases with its playbook. The order itself isn't affected.") },
            confirmButton = { TextButton(onClick = { onDelete(p.id); deleting = null }) { Text("Delete", color = ClaraColors.Danger) } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
}
