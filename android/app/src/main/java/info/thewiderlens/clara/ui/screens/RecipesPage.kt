package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.RecipeView
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.theme.ClaraColors

/** Recipes: the step-by-step jobs Clara follows. Built-in ones, and ones she learned from tasks that worked. */
@Composable
fun RecipesPage(state: UiState, onRefresh: () -> Unit, onDelete: (String) -> Unit, onBack: () -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    var open by remember { mutableStateOf<String?>(null) }
    var deleting by remember { mutableStateOf<RecipeView?>(null) }
    PageScaffold("Recipes", onBack) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            Text("When a request matches a recipe, Clara follows its steps in order and picks up where she left off after you answer. " +
                "She learns new ones from multi-step jobs that worked, and uses a learned recipe once it has worked twice.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
            Spacer(Modifier.height(10.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.recipes.isEmpty()) item { Text("Loading…", color = ClaraColors.Muted) }
                items(state.recipes, key = { it.name }) { r ->
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel)
                            .border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp))
                            .clickable { open = if (open == r.name) null else r.name }.padding(14.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(r.title, style = MaterialTheme.typography.titleMedium)
                                Text(
                                    when {
                                        !r.learned -> "Built in · ${r.steps.size} steps"
                                        r.trusted -> "Learned · worked ${r.wins}× · in use"
                                        else -> "Learned · worked ${r.wins}× · used after it works twice"
                                    },
                                    style = MaterialTheme.typography.labelMedium, color = if (r.trusted) ClaraColors.Cyan else ClaraColors.Muted,
                                )
                            }
                            Text(if (open == r.name) "▾" else "›", color = ClaraColors.Muted)
                        }
                        if (open == r.name) {
                            Spacer(Modifier.height(8.dp))
                            r.steps.forEachIndexed { i, s ->
                                Text("${i + 1}. $s", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 2.dp))
                            }
                            if (r.examples.isNotEmpty()) {
                                Spacer(Modifier.height(6.dp))
                                Text("Used for: " + r.examples.joinToString(" · ") { "“$it”" }, style = MaterialTheme.typography.labelSmall,
                                    color = ClaraColors.Muted)
                            }
                            if (r.learned) TextButton(onClick = { deleting = r }) { Text("Delete", color = ClaraColors.Danger) }
                        }
                    }
                }
            }
        }
    }
    deleting?.let { r ->
        AlertDialog(
            onDismissRequest = { deleting = null }, containerColor = ClaraColors.Panel,
            title = { Text("Delete “${r.title}”?") },
            text = { Text("Clara stops following it. She may learn it again if the same kind of task works later.") },
            confirmButton = { TextButton(onClick = { onDelete(r.name); deleting = null }) { Text("Delete", color = ClaraColors.Danger) } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
}
