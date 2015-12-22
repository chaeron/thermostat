// By Andrzej Jan Taramina
// www.chaeron.com
// andrzej@chaeron.com
//

// Constructor for ScheduleEntry objects to hold data for all drawn objects.
// For now they will just be defined as rectangles.

function ScheduleEntry( hhmm, temp, ss ) {
  this.ss   = ss;
  this.hhmm = hhmm;
  this.temp = temp;
  this.y    = this.ss.imgY;

  this.x 	= this.xFromHHMM( hhmm ); 
}


// Draws this entry to a given context

ScheduleEntry.prototype.draw = function( ctx, selected ) {
  if( selected ) {
  	  ctx.drawImage(  this.ss.sel, this.x, this.y  );
      ctx.font = 'bold 8pt Arial';
	  ctx.fillStyle = "red";
  } else {
	  ctx.fillStyle = "black";
	  ctx.font = '8pt Arial';
	  ctx.drawImage(  this.ss.img, this.x, this.y  );
  }

  ctx.textAlign = "center";
  ctx.fillText( this.temp.toFixed( 1 ), this.x + this.ss.imgw / 2, this.y - 2 );

}

// Determine if a point is inside the entry's bounds

ScheduleEntry.prototype.contains = function( mx, my ) {
  // All we have to do is make sure the Mouse X,Y fall in the area between
  // the ponters's X and ( X + Width ) and its Y and ( Y + Height )

  return  ( this.x <= mx ) && ( this.x + this.ss.imgw >= mx ) &&
          ( this.y - 10 <= my ) && ( this.y + this.ss.imgh >= my );
}


// Set Entry x axis position

ScheduleEntry.prototype.setX = function( x ) {
  this.x = x;
  this.hhmm = this.hhmmFromX( x );
}


// Get X pos from HHMM

ScheduleEntry.prototype.xFromHHMM = function( hhmm ) {
  var x;

  var parts = hhmm.split( ":" );
  var hh    = parseInt( parts[ 0 ] );
  var mm    = parseInt( parts[ 1 ] );
  
  var incr  = ( hh * 60 + mm ) / this.ss.increment;

  var rel   = incr / ( 24 * 6 );

  x = Math.ceil( this.ss.lenX * rel ) + this.ss.margin.left - this.ss.imgw / 2;

  return x;
}


// Get HHMMX pos from x

ScheduleEntry.prototype.hhmmFromX = function( x ) {
  var hhmm;

  var normalized =  x - this.ss.margin.left + this.ss.imgw / 2;

  var increments = Math.floor( normalized / this.ss.lenX * 24 * 6 )

  var minutes    = increments * this.ss.increment;

  var hh		 = Math.floor( minutes / 60 );
  var mm         = minutes % 60

  var hhmm		 = ( "00" + hh ).substr( -2 ) + ":" + ( "00" + mm ).substr( -2 )

  return hhmm;
}


function ScheduleSlider( schedule, day, canvas, imgref, selref, otherSS ) {
  // **** First some setup! ****
  
  this.canvas 	= canvas;
  this.width 	= canvas.width;
  this.height 	= canvas.height;
  this.ctx 		= canvas.getContext( '2d' );
  this.margin  	= { top: 10, left: 20, right: 20, bottom: 10 };

  this.schedule = schedule;
  this.day      = day;

  this.otherSS 	= otherSS;
  
  this.img 		= document.getElementById( imgref );
  this.sel 		= document.getElementById( selref );
  this.imgh		= this.img.height;
  this.imgw 	= this.img.width;

  this.minX 	= this.margin.left - this.imgw / 2;
  this.maxX 	= this.width - this.margin.right - this.imgw / 2 - 1;
  this.lenX 	= this.width - this.margin.left - this.margin.right;

  this.imgY 	= 33;

  this.increment = 10; 	// minutes

  this.se  		= new ScheduleEntry( "00:00", 0.0, this );

  this.entryDetails = $( "#entryDetails" );
  this.entrySlider  = $( "#slider-horizontal" );
  this.entryTime    = $( "#time" );
  this.entryTemp    = $( "#temp" );

  this.touchTimer 	= null;

  // This complicates things a little but but fixes mouse co-ordinate problems
  // when there's a border or padding. See getMouse for more detail

  var stylePaddingLeft, stylePaddingTop, styleBorderLeft, styleBorderTop;
  if( document.defaultView && document.defaultView.getComputedStyle ) {
    this.stylePaddingLeft = parseInt( document.defaultView.getComputedStyle( canvas, null )['paddingLeft'], 10 )      || 0;
    this.stylePaddingTop  = parseInt( document.defaultView.getComputedStyle( canvas, null )['paddingTop'], 10 )       || 0;
    this.styleBorderLeft  = parseInt( document.defaultView.getComputedStyle( canvas, null )['borderLeftWidth'], 10 )  || 0;
    this.styleBorderTop   = parseInt( document.defaultView.getComputedStyle( canvas, null )['borderTopWidth'], 10 )   || 0;
  }

  // Some pages have fixed-position bars at the top or left of the page
  // They will mess up mouse coordinates and this fixes that

  var html = document.body.parentNode;
  this.htmlTop = html.offsetTop;
  this.htmlLeft = html.offsetLeft;

  // **** Keep track of state! ****
  
  this.valid = false; 		// when set to false, the canvas will redraw everything
  this.entries = [];  		// the collection of things to be drawn
  this.dragging = false; 	// Keep track of when we are dragging
  							// the current selected object. In the future we could turn this into an array for multiple selection
  this.selection = null;
  this.dragoffx = 0; 		// See mousedown and mousemove events for explanation
  this.dragoffy = 0;
  
  // **** Then events! ****
  
  // This is an example of a closure!
  // Right here "this" means the ScheduleSlider. But we are making events on the Canvas itself,
  // and when the events are fired on the canvas the variable "this" is going to mean the canvas!
  // Since we still want to use this particular ScheduleSlider in the events we have to save a reference to it.
  // This is our reference!

  var thisSS = this;
  
  //fixes a problem where double clicking causes text to get selected on the canvas

  $( canvas ).on( 'selectstart', function( e ) { e.preventDefault(); return false; } );

  // Up, down, and move are for dragging
  $( canvas ).on( "mousedown touchstart", function( e ) {
	e.preventDefault();

	var mouse = thisSS.getMouse( e );
	var mx = mouse.x;
	var my = mouse.y;
	var entries = thisSS.entries;

	thisSS.selection = null;

	for( var i = entries.length - 1; i >= 0; i-- ) {
	  if( entries[i].contains( mx, my ) ) {
	    var mySel = entries[i];
	    // Keep track of where in the object we clicked
	    // so we can move it smoothly ( see mousemove )
	    thisSS.dragoffx = mx - mySel.x;
	    // thisSS.dragoffy = my - mySel.y;
	    thisSS.dragging = true;
	    thisSS.setSelected( mySel );
	    thisSS.valid = false;
		if( thisSS.touchTimer != null ) {
			clearTimeout( thisSS.touchTimer );
        	thisSS.touchTimer = null;
        }
		break;
	  }
	}

	if( thisSS.selection == null ) {
	  thisSS.setSelected( null ); // Make sure other SS's get deselected
	  thisSS.valid = false;

	  if( thisSS.touchTimer == null && e.type.indexOf( "touch" ) === 0 ) {
        thisSS.touchTimer = setTimeout( function () {
			thisSS.touchTimer = null;
        }, 500 )
      } else if( e.type.indexOf( "touch" ) === 0 ){
        clearTimeout( thisSS.touchTimer );
        thisSS.touchTimer = null;
        
		thisSS.handleDoubleClick( e );
      }	  
	}
  });

  $( canvas ).on( "mousemove touchmove",  function( e ) {
	e.preventDefault();

	if( thisSS.dragging ) {
	  var mouse = thisSS.getMouse( e );
	  // We don't want to drag the object by its top-left corner, we want to drag it
	  // from where we clicked. Thats why we saved the offset and use it here
	  thisSS.selection.setX( mouse.x - thisSS.dragoffx );

	  if( thisSS.selection.x < thisSS.minX ) {
		  thisSS.selection.setX( thisSS.minX );
	  } else if( thisSS.selection.x > thisSS.maxX ) {
		   thisSS.selection.setX( thisSS.maxX );
	  }

	  thisSS.entryTime.val( thisSS.selection.hhmm );

	  // thisSS.selection.y = mouse.y - thisSS.dragoffy;  // Y axis stays fixed!  
	  thisSS.valid = false; 	// Something's dragging so we must redraw
	}

  });

  
  $( canvas ).on( "mouseup touchend", function( e ) {
	e.preventDefault();
	thisSS.dragging = false;
  });


  // double click for making new entries

  $( canvas ).on( 'dblclick', function( e ) {
	thisSS.handleDoubleClick( e );
  });
  
  // **** Options! ****
  
  this.selectionColor = '#CC0000';
  this.selectionWidth = 2;  
  this.interval = 30;
  setInterval( function(  ) { thisSS.draw(  ); }, thisSS.interval );
}


ScheduleSlider.prototype.handleDoubleClick = function( e ) {
  var mouse = this.getMouse( e );
  this.setSelected( new ScheduleEntry( this.se.hhmmFromX( mouse.x - this.margin.left + this.imgw / 2 ), 21.0, this ) );
  this.addScheduleEntry( this.selection );
}


ScheduleSlider.prototype.addScheduleEntry = function( entry ) {
  this.entries.push( entry );
  this.valid = false;
}


ScheduleSlider.prototype.clear = function(  ) {
  this.ctx.clearRect( 0, 0, this.width, this.height );
}


// While draw is called as often as the INTERVAL variable demands,
// It only ever does something if the canvas gets invalidated by our code

ScheduleSlider.prototype.draw = function(  ) {
  // if our state is invalid, redraw and validate!

  if( !this.valid ) {
    var ctx = this.ctx;
    var entries = this.entries;
    this.clear();
    this.drawDecorators( ctx );
     
    // draw all entries

    var l = entries.length;
    for( var i = 0; i < l; i++ ) {
      var entry = entries[i];
      // We can skip the drawing of elements that have moved off the screen:
      if( entry.x > this.width || entry.y > this.height ||
          entry.x + this.imgw < 0 || entry.y + this.imgh < 0 ) continue;

      entries[i].draw( ctx, entries[ i ] == this.selection );
    }
    
    this.valid = true;
  }
}


// Draw all the decorators (label, axis, etc.)

ScheduleSlider.prototype.drawDecorators = function( ctx ) {
	// Draw Day Label
	ctx.font = 'bold 10pt Arial';
	ctx.fillStyle = "black";
	ctx.textAlign = "left";
    ctx.fillText( this.day, 5, 15 );

	// Draw x-axis
	ctx.strokeStyle = '#777777';
	ctx.beginPath();
    ctx.moveTo( this.margin.left, this.imgY + 25 );
    ctx.lineTo( this.margin.left + this.lenX, this.imgY + 25 );
    ctx.stroke();
    ctx.closePath();

    // Draw x-axis labels and ticks
    var xInc =  this.lenX / 24;
    var xPos = this.margin.left;
	ctx.font = '8pt Arial';
	ctx.fillStyle = '#777777';
	ctx.textAlign = "center";
	for( hh = 0; hh < 24; hh++ ) {
		txt = ( "00" + hh ).substr( -2 );
        txtSize = ctx.measureText( txt );
		ctx.fillText( txt, Math.round( xPos ) + 1, this.imgY + 38 );

		ctx.beginPath();
		ctx.moveTo( Math.round( xPos ) + 1, this.imgY + 24 );
		ctx.lineTo( Math.round( xPos ) + 1, this.imgY + 21 );
		ctx.stroke();
		ctx.closePath();

		xPos += xInc;		
	}
}

// set the selected entry

ScheduleSlider.prototype.setSelected = function( sel, otherSSSelect ) {
	otherSSSelect = typeof otherSSSelect !== 'undefined' ? otherSSSelect : false;

	this.selection = sel; 

    if( sel ) {
		this.entryDetails.show();
        this.entryTime.val( sel.hhmm );
		this.entrySlider.slider( "option", "value", sel.temp );
		this.entryTemp.val( sel.temp.toFixed( 1 ) );
		this.entryDetails.data( 'selectedScheduleEntry', sel );
	} else {
		if( !otherSSSelect ) {
			this.entryDetails.hide();
			this.entryDetails.data( 'selectedScheduleEntry', null );
		} else {
			this.valid = false;
		}
	}   

	if( !otherSSSelect ) {
		for( i = 0; i < this.otherSS.length; i++ ) {
			if( this.otherSS[ i ] != this ) {
				this.otherSS[ i ].setSelected( null, true );
			}
		} 
	} 
}


// delete the selected entry

ScheduleSlider.prototype.deleteSelected = function() {
	var sel = this.selection;

	if( sel ) {
		for( i = 0; i < this.entries.length; i++ ) {
			if( this.entries[ i ] == sel ) {
				this.entries.splice( i, 1 );
				break;
			}
		}

		this.setSelected( null );
	}
}


// Creates an object with x and y defined, set to the mouse position relative to the state's canvas
// If you wanna be super-correct this can be tricky, we have to worry about padding and borders

ScheduleSlider.prototype.getMouse = function( e ) {
  var element = this.canvas, offsetX = 0, offsetY = 0, mx, my;
  
  // Compute the total offset

  if( element.offsetParent !== undefined ) {
    do {
      offsetX += element.offsetLeft;
      offsetY += element.offsetTop;
    } while( ( element = element.offsetParent ) );
  }

  // Add padding and border style widths to offset
  // Also add the <html> offsets in case there's a position:fixed bar

  offsetX += this.stylePaddingLeft + this.styleBorderLeft + this.htmlLeft;
  offsetY += this.stylePaddingTop + this.styleBorderTop + this.htmlTop;

  var pageX;
  var pageY;

  if( e.originalEvent && e.originalEvent.touches ) {
	  pageX = e.originalEvent.touches[0].pageX;
	  pageY = e.originalEvent.touches[0].pageY;
  } else {
	  pageX = e.pageX;
      pageY = e.pageY;
  }

  mx = pageX - offsetX;
  my = pageY - offsetY;
  
  // We return a simple javascript object ( a hash ) with x and y defined

  return { x: mx, y: my };
}


