// AutoSiteMap Figma Plugin — Sandbox Code
// Receives manifest + screenshot data from ui.html and builds the sitemap diagram.

figma.showUI(__html__, { width: 450, height: 500, title: 'AutoSiteMap Import' });

let manifest = null;
const imageBytes = {};

figma.ui.onmessage = async (msg) => {
  if (msg.type === 'manifest') {
    manifest = msg.data;
  } else if (msg.type === 'image') {
    imageBytes[msg.stateId] = msg.data;
  } else if (msg.type === 'all-images-sent') {
    await buildSiteMap();
  }
};

async function buildSiteMap() {
  let rootFrame = null;

  try {
    sendProgress('Loading fonts...', 5);
    await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
    await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });

    // Defaults from manifest or fallback
    const diagram = manifest.diagram || {};
    const cardPadding = diagram.card_padding || 20;
    const fontSize = diagram.font_size || 14;
    const titleFontSize = diagram.title_font_size || 18;

    // Position the root frame away from existing content
    const existingNodes = figma.currentPage.children;
    let offsetX = 100;
    if (existingNodes.length > 0) {
      let maxRight = 0;
      for (const node of existingNodes) {
        const right = node.x + node.width;
        if (right > maxRight) maxRight = right;
      }
      offsetX = maxRight + 200;
    }

    // Create root frame
    const timestamp = manifest.generated_at || new Date().toISOString();
    const siteName = manifest.site_name || 'Unknown';
    rootFrame = figma.createFrame();
    rootFrame.name = 'AutoSiteMap: ' + siteName + ' — ' + timestamp;
    rootFrame.x = offsetX;
    rootFrame.y = 100;
    rootFrame.fills = [{ type: 'SOLID', color: { r: 0.98, g: 0.98, b: 0.98 } }];
    rootFrame.clipsContent = false;

    // Index states by id for lookups
    const statesById = {};
    const states = manifest.states || [];
    for (const s of states) {
      statesById[s.id] = s;
    }

    // Create card nodes
    const cardFrames = {};
    const totalStates = states.length;

    for (let i = 0; i < totalStates; i++) {
      const state = states[i];
      sendProgress('Creating card ' + (i + 1) + ' of ' + totalStates + '...', 10 + Math.round((i / totalStates) * 50));

      const cardWidth = state.width || 400;
      const screenshotHeight = state.screenshot_height || (cardWidth * 0.5625);
      const labelHeight = state.height ? (state.height - screenshotHeight) : 60;

      const card = figma.createFrame();
      card.name = state.label || state.id;
      card.x = state.x || 0;
      card.y = state.y || 0;
      card.resize(cardWidth, screenshotHeight + labelHeight);
      card.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
      card.strokes = [{ type: 'SOLID', color: { r: 0.85, g: 0.85, b: 0.85 } }];
      card.strokeWeight = 1;
      card.cornerRadius = 4;
      card.clipsContent = true;
      rootFrame.appendChild(card);
      cardFrames[state.id] = card;

      // Screenshot rectangle
      const imgRect = figma.createRectangle();
      imgRect.name = 'screenshot';
      imgRect.x = 0;
      imgRect.y = 0;
      imgRect.resize(cardWidth, screenshotHeight);

      if (imageBytes[state.id]) {
        try {
          const img = figma.createImage(new Uint8Array(imageBytes[state.id]));
          imgRect.fills = [{
            type: 'IMAGE',
            imageHash: img.hash,
            scaleMode: 'FIT',
          }];
        } catch (imgErr) {
          // If image creation fails, show a placeholder
          imgRect.fills = [{ type: 'SOLID', color: { r: 0.93, g: 0.93, b: 0.93 } }];
        }
      } else {
        imgRect.fills = [{ type: 'SOLID', color: { r: 0.93, g: 0.93, b: 0.93 } }];
      }
      card.appendChild(imgRect);

      // Label area below screenshot
      const labelY = screenshotHeight + 4;
      const textPadding = 8;

      // URL text with hyperlink
      if (state.url) {
        const urlText = figma.createText();
        urlText.name = 'url';
        urlText.x = textPadding;
        urlText.y = labelY;
        urlText.resize(cardWidth - textPadding * 2, fontSize + 4);
        urlText.fontName = { family: 'Inter', style: 'Regular' };
        urlText.fontSize = fontSize;
        urlText.characters = state.url;
        urlText.fills = [{ type: 'SOLID', color: { r: 0.07, g: 0.47, b: 0.85 } }];
        urlText.textDecoration = 'UNDERLINE';
        urlText.textAutoResize = 'HEIGHT';
        try {
          urlText.setRangeHyperlink(0, state.url.length, { type: 'URL', value: state.url });
        } catch (_) {
          // Hyperlink may fail if URL is redacted or invalid
        }
        card.appendChild(urlText);
      }

      // Title text (bold)
      if (state.title) {
        const titleText = figma.createText();
        titleText.name = 'title';
        titleText.x = textPadding;
        titleText.y = labelY + fontSize + 6;
        titleText.resize(cardWidth - textPadding * 2, titleFontSize + 4);
        titleText.fontName = { family: 'Inter', style: 'Bold' };
        titleText.fontSize = titleFontSize;
        titleText.characters = state.title;
        titleText.fills = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.1 } }];
        titleText.textAutoResize = 'HEIGHT';
        card.appendChild(titleText);
      }

      // Controls summary (gray, small)
      if (state.controls_summary) {
        const ctrlText = figma.createText();
        ctrlText.name = 'controls';
        ctrlText.x = textPadding;
        ctrlText.y = labelY + fontSize + 6 + (state.title ? titleFontSize + 6 : 0);
        ctrlText.resize(cardWidth - textPadding * 2, fontSize);
        ctrlText.fontName = { family: 'Inter', style: 'Regular' };
        ctrlText.fontSize = Math.max(fontSize - 2, 10);
        ctrlText.characters = state.controls_summary;
        ctrlText.fills = [{ type: 'SOLID', color: { r: 0.55, g: 0.55, b: 0.55 } }];
        ctrlText.textAutoResize = 'HEIGHT';
        card.appendChild(ctrlText);
      }
    }

    // Create connections
    const connections = manifest.connections || [];
    const totalConns = connections.length;

    for (let i = 0; i < totalConns; i++) {
      const conn = connections[i];
      sendProgress('Creating connection ' + (i + 1) + ' of ' + totalConns + '...', 60 + Math.round((i / totalConns) * 30));

      const sx = conn.source_port.x;
      const sy = conn.source_port.y;
      const tx = conn.target_port.x;
      const ty = conn.target_port.y;

      // Create a VectorNode for the arrow line
      const arrow = figma.createVector();
      arrow.name = conn.label ? ('arrow: ' + conn.label) : ('arrow: ' + conn.source_id + ' -> ' + conn.target_id);

      // Compute bounding box for the vector
      const minX = Math.min(sx, tx);
      const minY = Math.min(sy, ty);
      const width = Math.max(Math.abs(tx - sx), 1);
      const height = Math.max(Math.abs(ty - sy), 1);

      arrow.x = minX;
      arrow.y = minY;
      arrow.resize(width, height);

      // Build vector network: two vertices connected by one segment
      const localSx = sx - minX;
      const localSy = sy - minY;
      const localTx = tx - minX;
      const localTy = ty - minY;

      try {
        await arrow.setVectorNetworkAsync({
          vertices: [
            { x: localSx, y: localSy, strokeCap: 'NONE' },
            { x: localTx, y: localTy, strokeCap: 'ARROW_LINES' },
          ],
          segments: [
            {
              start: 0,
              end: 1,
              tangentStart: { x: 0, y: 0 },
              tangentEnd: { x: 0, y: 0 },
            },
          ],
          regions: [],
        });
      } catch (_) {
        // Fallback: skip this arrow if vector network fails
        arrow.remove();
        continue;
      }

      // Style based on edge type
      if (conn.is_tree_edge) {
        arrow.strokes = [{ type: 'SOLID', color: { r: 0.2, g: 0.2, b: 0.2 } }];
        arrow.strokeWeight = 2;
        arrow.dashPattern = [];
      } else {
        // Cross-link: dashed, blue-gray
        arrow.strokes = [{ type: 'SOLID', color: { r: 0.467, g: 0.467, b: 0.667 } }];
        arrow.strokeWeight = 1.5;
        arrow.dashPattern = [8, 4];
      }

      arrow.fills = [];
      rootFrame.appendChild(arrow);

      // Connection label at midpoint
      if (conn.label) {
        const midX = (sx + tx) / 2;
        const midY = (sy + ty) / 2;

        const labelText = figma.createText();
        labelText.name = 'label: ' + conn.label;
        labelText.x = midX + 4;
        labelText.y = midY - fontSize / 2;
        labelText.fontName = { family: 'Inter', style: 'Regular' };
        labelText.fontSize = Math.max(fontSize - 2, 10);
        labelText.characters = conn.label;
        labelText.textAutoResize = 'WIDTH_AND_HEIGHT';

        if (conn.is_tree_edge) {
          labelText.fills = [{ type: 'SOLID', color: { r: 0.3, g: 0.3, b: 0.3 } }];
        } else {
          labelText.fills = [{ type: 'SOLID', color: { r: 0.4, g: 0.4, b: 0.6 } }];
        }

        rootFrame.appendChild(labelText);
      }
    }

    // Resize root frame to encompass all content with padding
    sendProgress('Finalizing layout...', 95);

    let maxRight = 0;
    let maxBottom = 0;
    for (let i = 0; i < rootFrame.children.length; i++) {
      const child = rootFrame.children[i];
      const r = child.x + child.width;
      const b = child.y + child.height;
      if (r > maxRight) maxRight = r;
      if (b > maxBottom) maxBottom = b;
    }

    rootFrame.resize(
      Math.max(maxRight + cardPadding, 400),
      Math.max(maxBottom + cardPadding, 300)
    );

    // Scroll into view
    figma.viewport.scrollAndZoomIntoView([rootFrame]);

    const summary = manifest.summary || {};
    figma.ui.postMessage({
      type: 'success',
      message: 'Import complete! Created ' + (states.length) + ' cards and ' + (connections.length) + ' connections.'
        + (summary.termination ? ' (Crawl ended: ' + summary.termination + ')' : ''),
    });

    figma.closePlugin();

  } catch (err) {
    if (rootFrame) {
      try { rootFrame.remove(); } catch (_) {}
    }
    figma.ui.postMessage({
      type: 'error',
      message: err.message || String(err),
    });
  }
}

function sendProgress(message, percent) {
  figma.ui.postMessage({ type: 'progress', message: message, percent: percent });
}
